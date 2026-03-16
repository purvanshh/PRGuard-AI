"""FastAPI-powered GitHub webhook server for PRGuard AI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from config.settings import settings
from analysis.repo_indexer import initialize_repo_index
from github.github_client import (
    format_pr_review,
    get_pr_diff,
    post_pr_comment,
    post_inline_comment,
)
from observability.logging import fetch_pr_logs, log_agent_execution
from queue.task_queue import (
    run_arbitrator,
    run_logic_agent,
    run_security_agent,
    run_style_agent,
)
from schemas.agent_output import AgentOutput

logger = logging.getLogger(__name__)

app = FastAPI(title="PRGuard AI Webhook Server", version="0.1.0")


def verify_github_signature(
    payload: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    """
    Verify the GitHub webhook payload signature.
    """
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Hub-Signature-256 header.",
        )

    try:
        algo, received_sig = signature_header.split("=", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Hub-Signature-256 header format.",
        ) from exc

    if algo != "sha256":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported signature algorithm.",
        )

    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    expected_sig = mac.hexdigest()
    if not hmac.compare_digest(expected_sig, received_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature.",
        )


async def get_raw_body(request: Request) -> bytes:
    """Retrieve raw request body for signature verification."""
    return await request.body()


@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    raw_body: bytes = Depends(get_raw_body),
) -> Dict[str, Any]:
    """
    GitHub webhook endpoint.
    """
    verify_github_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body.") from exc

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event {x_github_event} not supported"}

    action = payload.get("action")
    if action not in {"opened", "synchronize", "ready_for_review"}:
        return {"status": "ignored", "reason": f"action {action} not supported"}

    repo = payload["repository"]["full_name"]
    pr_number = payload["number"]
    pr_id = f"{repo}#{pr_number}"

    diff_text = get_pr_diff(repo_full_name=repo, pr_number=pr_number)

    # Initialize repository index for style retrieval.
    initialize_repo_index(repo_path=".")

    repo_metadata: Dict[str, Any] = {
        "repository": repo,
        "pr_number": pr_number,
        "action": action,
        "pr_id": pr_id,
    }

    # Enqueue Celery tasks and wait for completion (tasks execute in parallel).
    style_started = time.time()
    style_result = run_style_agent.delay(diff_text, repo_metadata)
    logic_started = time.time()
    logic_result = run_logic_agent.delay(diff_text, repo_metadata)
    security_started = time.time()
    security_result = run_security_agent.delay(diff_text, repo_metadata)

    style_output_dict = style_result.get(timeout=60)
    style_finished = time.time()
    logic_output_dict = logic_result.get(timeout=60)
    logic_finished = time.time()
    security_output_dict = security_result.get(timeout=60)
    security_finished = time.time()

    style_output = AgentOutput(**style_output_dict)
    logic_output = AgentOutput(**logic_output_dict)
    security_output = AgentOutput(**security_output_dict)

    # Log agent executions.
    log_agent_execution(
        pr_id,
        "style",
        style_started,
        style_finished,
        style_output_dict,
        execution_duration=style_finished - style_started,
        agent_order=1,
    )
    log_agent_execution(
        pr_id,
        "logic",
        logic_started,
        logic_finished,
        logic_output_dict,
        execution_duration=logic_finished - logic_started,
        agent_order=2,
    )
    log_agent_execution(
        pr_id,
        "security",
        security_started,
        security_finished,
        security_output_dict,
        execution_duration=security_finished - security_started,
        agent_order=3,
    )

    # Run arbitrator as a Celery task.
    arb_started = time.time()
    arb_result = run_arbitrator.delay(
        [
            style_output_dict,
            logic_output_dict,
            security_output_dict,
        ]
    )
    arb_output = arb_result.get(timeout=60)
    arb_finished = time.time()
    log_agent_execution(
        pr_id,
        "arbitrator",
        arb_started,
        arb_finished,
        arb_output,
        execution_duration=arb_finished - arb_started,
        agent_order=4,
    )

    comment_body = format_pr_review(arb_output)
    post_pr_comment(repo_full_name=repo, pr_number=pr_number, body=comment_body)

    # Post inline comments for medium/high severity issues (up to 10).
    inline_count = 0
    for issue in arb_output.get("issues", []):
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

    return {"status": "ok", "overall_confidence": arb_output.get("overall_confidence", 0.0)}


@app.get("/review/{pr_id}")
async def get_review(pr_id: str) -> Dict[str, Any]:
    """
    Replay endpoint returning agent outputs and analysis trace for a PR.
    """
    logs = fetch_pr_logs(pr_id)
    if not logs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logs found for PR.")
    return {"pr_id": pr_id, "logs": logs}


@app.get("/health")
async def health() -> Dict[str, str]:
    """
    Basic health check endpoint.
    """
    redis_status = "connected"
    openai_status = "configured" if bool(settings.openai_api_key) else "missing"
    return {
        "status": "ok",
        "redis": redis_status,
        "openai": openai_status,
    }


__all__ = ["app"]

