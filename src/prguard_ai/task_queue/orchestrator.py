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
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.db.redis_client import store_review_context, get_review_context
from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.gh_client.github_client import (
    format_pr_review,
    post_pr_comment,
    post_inline_comment,
)
from prguard_ai.observability.tracing import get_tracer

logger = logging.getLogger(__name__)
_TRACER = get_tracer("orchestrator")


@celery_app.task(name="task_queue.orchestrator.review_pr")
def review_pr(pr_id: str, diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Orchestrator task that coordinates multi-agent analysis and refinement passes."""
    repo_metadata = repo_metadata or {}
    repo = repo_metadata.get("repository", "unknown")
    pr_number = repo_metadata.get("pr_number", 0)

    with _TRACER.start_as_current_span("orchestrator_review_pr") as span:
        span.set_attribute("pr.id", pr_id)

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
        )
        store_review_context(pr_id, ctx)

        # 3. Launch refinement tasks in parallel
        refine_grp = group(
            refine_agent.s(pr_id, "style"),
            refine_agent.s(pr_id, "logic"),
            refine_agent.s(pr_id, "security"),
        )
        refine_result = refine_grp.apply_async()
        refined_outputs = refine_result.get(timeout=400)

        # Merge refined outputs back into context to ensure full consistency
        ctx = get_review_context(pr_id)
        if not ctx:
            raise ValueError(f"Context missing in Redis for PR {pr_id} after refinement")

        for out_dict in refined_outputs:
            output = AgentOutput(**out_dict)
            ctx.agent_outputs[output.agent] = output
        ctx.round = 1
        store_review_context(pr_id, ctx)

        # 4. Pass context to arbitrator
        report = arbitrate_confidence(ctx)
        report_dict = report.dict()
        report_dict["disagreements"] = getattr(report, "disagreements", [])

        # 5. Post final comments on GitHub
        comment_body = format_pr_review(report_dict)
        post_pr_comment(repo_full_name=repo, pr_number=pr_number, body=comment_body)

        # Post inline comments for medium/high severity issues
        inline_count = 0
        for issue in report_dict.get("issues", []):
            if inline_count >= 10:
                break
            severity = str(issue.get("severity", "")).lower()
            if severity not in {"medium", "high"}:
                continue
            file_path = issue.get("file_path")
            if not file_path:
                continue
            line = int(issue.get("line", 1))
            body = (
                "⚠ PRGuard AI\n"
                f"Issue: {issue.get('message')}\n"
                f"Evidence: {issue.get('evidence')}"
            )
            post_inline_comment(
                repo_full_name=repo,
                pr_number=pr_number,
                path=file_path,
                line=line,
                body=body,
            )
            inline_count += 1

        return report_dict
