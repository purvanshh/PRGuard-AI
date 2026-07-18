from __future__ import annotations

import logging
from typing import Any, Dict, List
from celery import group

from prguard_ai.task_queue.celery_app import (
    celery_app,
    run_style_agent,
    run_logic_agent,
    run_security_agent,
    refine_agent,
)
from prguard_ai.analysis.repo_sandbox import cleanup_repository
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.db.redis_client import store_review_context, get_review_context
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.observability.tracing import get_tracer

logger = logging.getLogger(__name__)
_TRACER = get_tracer("orchestrator")


@celery_app.task(name="task_queue.orchestrator.review_pr", time_limit=300, soft_time_limit=240)
def review_pr(prepared: Dict[str, Any], pr_id: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Orchestrator task that coordinates multi-agent analysis and refinement passes."""
    repo_metadata = repo_metadata or {}
    diff_text = prepared["diff_text"]
    sandbox_path = prepared.get("sandbox_path")
    if sandbox_path:
        repo_metadata = {**repo_metadata, "sandbox_path": sandbox_path}
    repo = repo_metadata.get("repository", "unknown")
    pr_number = repo_metadata.get("pr_number", 0)

    with _TRACER.start_as_current_span("orchestrator_review_pr") as span:
        span.set_attribute("pr.id", pr_id)
        try:
            # 1. Run the three initial agent tasks in parallel
            initial_group = group(
                run_style_agent.s(diff_text, repo_metadata),
                run_logic_agent.s(diff_text, repo_metadata),
                run_security_agent.s(diff_text, repo_metadata),
            )
            result = initial_group.apply_async()
            outputs = result.get(timeout=400)

            style_output = AgentOutput(**outputs[0])
            logic_output = AgentOutput(**outputs[1])
            security_output = AgentOutput(**outputs[2])

            # 2. Store their outputs in a ReviewContext (round=0)
            ctx = ReviewContext(
                pr_id=pr_id,
                diff_text=diff_text,
                repo_metadata=repo_metadata,
                agent_outputs={
                    "style": style_output,
                    "logic": logic_output,
                    "security": security_output,
                },
                round=0,
                sandbox_path=sandbox_path,
            )
            store_review_context(pr_id, ctx)

            # 3. Dialogue & Debate loop (up to max_rounds)
            max_rounds = 3
            consecutive_no_change_rounds = 0

            def _issues_changed(issues_a, issues_b) -> bool:
                if len(issues_a) != len(issues_b):
                    return True

                def _to_set(issues):
                    return {(i.line, i.severity, i.message, i.file_path) for i in issues}

                return _to_set(issues_a) != _to_set(issues_b)

            from prguard_ai.agents.coordinator import CoordinatorAgent
            from prguard_ai.schemas.context import DialogueTurn

            for round_num in range(1, max_rounds + 1):
                ctx.round = round_num
                moderation = CoordinatorAgent.moderate_round(ctx)
                for critique in moderation.get("critiques", []):
                    ctx.dialogue.append(DialogueTurn(speaker="coordinator", message=critique))
                ctx.coordinator_guidance.extend(moderation.get("steering_questions", []))
                for question in moderation.get("steering_questions", []):
                    ctx.dialogue.append(DialogueTurn(speaker="coordinator", message=question))
                store_review_context(pr_id, ctx)

                refine_grp = group(
                    refine_agent.s(pr_id, "style"),
                    refine_agent.s(pr_id, "logic"),
                    refine_agent.s(pr_id, "security"),
                )
                refine_result = refine_grp.apply_async()
                refined_results = refine_result.get(timeout=400)

                ctx = get_review_context(pr_id)
                if not ctx:
                    raise ValueError(f"Context missing in Redis for PR {pr_id} during round {round_num}")

                round_changed = False
                for res in refined_results:
                    msg = res.get("message") or ""
                    out_dict = res.get("refined_output")
                    if not out_dict:
                        continue
                    output = AgentOutput(**out_dict)
                    prev_output = ctx.agent_outputs.get(output.agent)

                    if msg.strip():
                        ctx.dialogue.append(DialogueTurn(speaker=output.agent, message=msg))
                    if not prev_output or _issues_changed(prev_output.issues, output.issues):
                        round_changed = True

                    ctx.agent_outputs[output.agent] = output

                if not round_changed:
                    consecutive_no_change_rounds += 1
                else:
                    consecutive_no_change_rounds = 0

                store_review_context(pr_id, ctx)
                if CoordinatorAgent.should_stop(
                    ctx,
                    max_rounds=max_rounds,
                    consecutive_no_change_rounds=consecutive_no_change_rounds,
                ):
                    break

            report = arbitrate_confidence(ctx)
            report_dict = report.model_dump()
            report_dict["disagreements"] = getattr(report, "disagreements", [])
            if sandbox_path:
                report_dict["sandbox_path"] = sandbox_path
            report_dict["repo"] = repo
            report_dict["pr_number"] = pr_number
            return report_dict
        except Exception:
            if sandbox_path:
                cleanup_repository(sandbox_path)
            raise
