"""Asynchronous Celery tasks for PRGuard AI."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from prguard_ai.task_queue.celery_app import celery_app
from prguard_ai.gh_client.github_client import post_pr_comment, post_inline_comment, format_pr_review
from prguard_ai.task_queue.task_registry import complete_pr_processing
from prguard_ai.observability.metrics import DEAD_LETTERED_TASKS, TOTAL_PRS_PROCESSED, REVIEW_CONFIDENCE
from prguard_ai.human_review import human_review_queue
from prguard_ai.schemas.pr_report import PullRequestReport

logger = logging.getLogger(__name__)
_DLQ_KEY = "prguard:dlq"


def _enqueue_dead_letter(payload: dict) -> None:
    from prguard_ai.task_queue.redis_client import get_redis

    get_redis().rpush(_DLQ_KEY, json.dumps(payload))
    DEAD_LETTERED_TASKS.inc()


@celery_app.task(name="task_queue.tasks.prepare_repository")
def prepare_repository(pr_id: str, repo: str, pr_number: int, payload: dict) -> dict:
    """
    Clone, index, and warm code graph asynchronously in a background task,
    then return the PR diff text and sandbox path.
    """
    from prguard_ai.gh_client.github_client import get_pr_diff
    from prguard_ai.analysis.repo_sandbox import clone_repository, cleanup_repository
    from prguard_ai.analysis.repo_indexer import initialize_repo_index
    from prguard_ai.analysis.code_graph import build_code_graph

    logger.info("Preparing repository asynchronously for %s", pr_id)
    diff_text = get_pr_diff(repo_full_name=repo, pr_number=pr_number)

    sandbox_path = None
    try:
        repo_url = payload.get("repository", {}).get("clone_url") or payload.get("repository", {}).get("html_url")
        if repo_url:
            sandbox = clone_repository(repo_url=repo_url, pr_number=pr_number, repo_full_name=repo)
            sandbox_path = str(sandbox.temp_path)
            initialize_repo_index(repo_path=sandbox_path)
            try:
                build_code_graph(sandbox_path)
            except Exception:
                logger.warning("Failed to build code graph for repository %s", repo)
    except Exception as exc:
        if sandbox_path:
            cleanup_repository(sandbox_path)
        logger.exception("Failed to prepare repository for PR %s", pr_id)
        raise exc

    return {"diff_text": diff_text, "sandbox_path": sandbox_path}


@celery_app.task(name="task_queue.tasks.post_review")
def post_review(report_dict: dict, repo: str, pr_number: int) -> dict:
    """
    Post the final review comments and inline comments to GitHub asynchronously.
    """
    pr_id = f"{repo}#{pr_number}"
    logger.info("Posting final review comment for %s", pr_id)
    sandbox_path = report_dict.pop("sandbox_path", None)

    try:
        for issue in report_dict.get("issues", []):
            if isinstance(issue, dict):
                issue.setdefault("confidence_source", "inferred")
        report_model = PullRequestReport.model_validate(report_dict)
        if not human_review_queue.should_auto_post(report_model):
            pending = human_review_queue.enqueue(
                pr_id,
                report_model,
                reason="confidence_below_auto_post_threshold",
            )
            report_dict["human_review_status"] = "pending"
            report_dict["human_review_id"] = pending.review_id
            return report_dict

        comment_body = format_pr_review(report_dict)
        post_pr_comment(repo_full_name=repo, pr_number=pr_number, body=comment_body)

        # Post inline comments for medium/high severity issues (up to 10 comments)
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

        # Track metrics
        TOTAL_PRS_PROCESSED.inc()
        REVIEW_CONFIDENCE.observe(float(report_dict.get("overall_confidence", 0.0)))

    finally:
        if sandbox_path:
            from prguard_ai.analysis.repo_sandbox import cleanup_repository

            cleanup_repository(sandbox_path)
        # Always mark PR processing as complete
        complete_pr_processing(pr_id)

    return report_dict


@celery_app.task(name="task_queue.tasks.on_task_failure")
def on_task_failure(*args: Any, pr_id: str | None = None, **kwargs: Any) -> None:
    """
    Callback executed when any task in the PR review workflow fails.
    Cleans up the PR processing status and logs the error.
    """
    logger.error("PRGuard processing workflow failed for PR %s. args=%s, kwargs=%s", pr_id, args, kwargs)
    _enqueue_dead_letter(
        {
            "pr_id": pr_id,
            "args": [str(arg) for arg in args],
            "kwargs": {key: str(value) for key, value in kwargs.items()},
        }
    )
    if pr_id:
        complete_pr_processing(pr_id)
