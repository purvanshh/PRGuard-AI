from __future__ import annotations

import logging
from typing import Any, Dict, List
from celery import chord, group

from prguard_ai.task_queue.celery_app import (
    celery_app,
    run_style_agent,
    run_logic_agent,
    run_security_agent,
    refine_agent,
    on_chord_error,
)
from prguard_ai.analysis.repo_sandbox import cleanup_repository
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.db.redis_client import store_review_context, get_review_context
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.observability.tracing import get_tracer
from prguard_ai.task_queue.tasks import on_task_failure, post_review

logger = logging.getLogger(__name__)
_TRACER = get_tracer("orchestrator")


@celery_app.task(name="task_queue.orchestrator.review_pr", time_limit=300, soft_time_limit=240)
def review_pr(prepared: Dict[str, Any], pr_id: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Start the non-blocking multi-agent review workflow."""
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
            initial_group = group(
                run_style_agent.s(diff_text, repo_metadata),
                run_logic_agent.s(diff_text, repo_metadata),
                run_security_agent.s(diff_text, repo_metadata),
            )
            workflow = chord(
                initial_group,
                process_initial_agent_outputs.s(pr_id, diff_text, repo_metadata, sandbox_path, repo, pr_number),
            )
            result = workflow.apply_async(link_error=on_chord_error.s(pr_id=pr_id))
            span.add_event("initial_agent_chord_enqueued", {"chord_id": result.id or ""})
            return {"status": "enqueued", "pr_id": pr_id, "workflow_id": result.id}
        except Exception:
            if sandbox_path:
                cleanup_repository(sandbox_path)
            raise


@celery_app.task(
    name="task_queue.orchestrator.process_initial_agent_outputs",
    bind=True,
    max_retries=3,
    time_limit=300,
    soft_time_limit=240,
)
def process_initial_agent_outputs(
    self,
    outputs: List[Dict[str, Any]],
    pr_id: str,
    diff_text: str,
    repo_metadata: Dict[str, Any],
    sandbox_path: str | None,
    repo: str,
    pr_number: int,
) -> dict:
    """Store initial agent results and start the first refinement chord."""
    try:
        agent_outputs = {
            AgentOutput.model_validate(output).agent: AgentOutput.model_validate(output)
            for output in outputs
        }

        ctx = ReviewContext(
            pr_id=pr_id,
            diff_text=diff_text,
            repo_metadata=repo_metadata,
            agent_outputs=agent_outputs,
            round=0,
            sandbox_path=sandbox_path,
        )
        store_review_context(pr_id, ctx)
        return _dispatch_refinement_round(pr_id, repo, pr_number, round_num=1, consecutive_no_change_rounds=0)
    except Exception as exc:
        from prguard_ai.task_queue.celery_app import _enqueue_orchestrator_dlq

        logger.exception("process_initial_agent_outputs failed for PR %s", pr_id)
        _enqueue_orchestrator_dlq(
            {
                "task": "process_initial_agent_outputs",
                "pr_id": pr_id,
                "error": str(exc),
            }
        )
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(
    name="task_queue.orchestrator.process_refinement_outputs",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    time_limit=300,
    soft_time_limit=240,
)
def process_refinement_outputs(
    refined_results: List[Dict[str, Any]],
    pr_id: str,
    repo: str,
    pr_number: int,
    round_num: int,
    consecutive_no_change_rounds: int,
) -> dict:
    """Apply refinement results, continue if needed, otherwise post the final report."""
    from prguard_ai.agents.coordinator import CoordinatorAgent
    from prguard_ai.schemas.context import DialogueTurn

    ctx = get_review_context(pr_id)
    if not ctx:
        raise ValueError(f"Context missing in Redis for PR {pr_id} during round {round_num}")

    round_changed = False
    for res in refined_results:
        msg = res.get("message") or ""
        out_dict = res.get("refined_output")
        if not out_dict:
            continue
        output = AgentOutput.model_validate(out_dict)
        prev_output = ctx.agent_outputs.get(output.agent)

        if msg.strip():
            ctx.dialogue.append(DialogueTurn(speaker=output.agent, message=msg))
        if not prev_output or _issues_changed(prev_output.issues, output.issues):
            round_changed = True

        ctx.agent_outputs[output.agent] = output

    consecutive_no_change_rounds = 0 if round_changed else consecutive_no_change_rounds + 1
    store_review_context(pr_id, ctx)

    max_rounds = 3
    if CoordinatorAgent.should_stop(
        ctx,
        max_rounds=max_rounds,
        consecutive_no_change_rounds=consecutive_no_change_rounds,
    ):
        return _finalize_review(ctx, repo, pr_number)

    return _dispatch_refinement_round(
        pr_id,
        repo,
        pr_number,
        round_num=round_num + 1,
        consecutive_no_change_rounds=consecutive_no_change_rounds,
    )


def _issues_changed(issues_a, issues_b) -> bool:
    if len(issues_a) != len(issues_b):
        return True

    def _to_set(issues):
        return {(i.line, i.severity, i.message, i.file_path) for i in issues}

    return _to_set(issues_a) != _to_set(issues_b)


def _dispatch_refinement_round(
    pr_id: str,
    repo: str,
    pr_number: int,
    round_num: int,
    consecutive_no_change_rounds: int,
) -> dict:
    from prguard_ai.agents.coordinator import CoordinatorAgent
    from prguard_ai.schemas.context import DialogueTurn

    ctx = get_review_context(pr_id)
    if not ctx:
        raise ValueError(f"Context missing in Redis for PR {pr_id} before round {round_num}")

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
    workflow = chord(
        refine_grp,
        process_refinement_outputs.s(pr_id, repo, pr_number, round_num, consecutive_no_change_rounds),
    )
    result = workflow.apply_async(link_error=on_task_failure.s(pr_id=pr_id))
    return {"status": "refinement_enqueued", "pr_id": pr_id, "round": round_num, "workflow_id": result.id}


def _finalize_review(ctx: ReviewContext, repo: str, pr_number: int) -> dict:
    report = arbitrate_confidence(ctx)
    report_dict = report.model_dump()
    report_dict["disagreements"] = getattr(report, "disagreements", [])
    if ctx.sandbox_path:
        report_dict["sandbox_path"] = ctx.sandbox_path
    report_dict["repo"] = repo
    report_dict["pr_number"] = pr_number
    post_result = post_review.apply_async((report_dict, repo, pr_number), link_error=on_task_failure.s(pr_id=ctx.pr_id))
    return {"status": "post_review_enqueued", "pr_id": ctx.pr_id, "workflow_id": post_result.id}
