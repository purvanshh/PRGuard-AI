"""FastAPI-powered GitHub webhook server for PRGuard AI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from config.settings import settings
from github.github_client import get_pr_diff, post_pr_comment
from queue.task_queue import run_style_agent, run_logic_agent, run_security_agent
from agents.arbitrator_agent import arbitrate_confidence
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

    GitHub sends the HMAC hexdigest signature in the X-Hub-Signature-256 header.
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

    Verifies the payload signature, parses pull request events, then enqueues
    Celery jobs to run analysis agents.
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

    diff_text = get_pr_diff(repo_full_name=repo, pr_number=pr_number)

    repo_metadata: Dict[str, Any] = {
        "repository": repo,
        "pr_number": pr_number,
        "action": action,
    }

    # Enqueue Celery tasks (synchronously wait for result in this minimal implementation).
    style_result = run_style_agent.delay(diff_text, repo_metadata)
    logic_result = run_logic_agent.delay(diff_text, repo_metadata)
    security_result = run_security_agent.delay(diff_text, repo_metadata)

    style_output = AgentOutput(**style_result.get(timeout=30))
    logic_output = AgentOutput(**logic_result.get(timeout=30))
    security_output = AgentOutput(**security_result.get(timeout=30))

    report = arbitrate_confidence([style_output, logic_output, security_output])

    comment_body = _format_report_comment(report.dict())
    post_pr_comment(repo_full_name=repo, pr_number=pr_number, body=comment_body)

    return {"status": "ok", "overall_confidence": report.overall_confidence}


def _format_report_comment(report: Dict[str, Any]) -> str:
    """
    Format a human-readable PR comment from a PullRequestReport-like dict.

    This is intentionally simple and can be replaced with a richer template later.
    """
    lines = [
        "## PRGuard AI Review",
        "",
        f"**Overall confidence:** {report.get('overall_confidence', 0.0):.2f}",
        "",
    ]

    issues = report.get("issues", [])
    if not issues:
        lines.append("No issues detected by agents.")
    else:
        lines.append("### Issues")
        for issue in issues:
            lines.append(
                f"- `{issue.get('severity', '').upper()}` "
                f"(line {issue.get('line')}): {issue.get('message')}"
            )

    return "\n".join(lines)


__all__ = ["app"]

