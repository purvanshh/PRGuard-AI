"""FastAPI-powered GitHub webhook server for PRGuard AI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from config.settings import settings
from analysis.repo_indexer import initialize_repo_index
from analysis.code_graph import build_code_graph
from analysis.repo_sandbox import RepoSandboxError, cleanup_repository, clone_repository
from github.github_client import (
    format_pr_review,
    get_pr_diff,
    post_pr_comment,
    post_inline_comment,
)
from observability.logging import fetch_pr_logs, log_agent_execution
from observability.event_stream import broker
from observability.metrics import (
    TOTAL_PRS_PROCESSED,
    AGENT_EXECUTION_TIME,
    REVIEW_CONFIDENCE,
)
from observability.tracing import get_tracer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi.responses import PlainTextResponse
from queue.task_queue import (
    run_arbitrator,
    run_logic_agent,
    run_security_agent,
    run_style_agent,
)
from schemas.agent_output import AgentOutput

logger = logging.getLogger(__name__)
_TRACER = get_tracer("webhook")

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

    with _TRACER.start_as_current_span("webhook_received") as span:
        span.set_attribute("pr.id", pr_id)
        span.set_attribute("repo.full_name", repo)
        span.set_attribute("pr.number", int(pr_number))
        span.set_attribute("pr.action", action or "")

        diff_text = get_pr_diff(repo_full_name=repo, pr_number=pr_number)

        sandbox_path: str | None = None
        try:
            try:
                repo_url = payload.get("repository", {}).get("clone_url") or payload.get("repository", {}).get("html_url")
                sandbox = clone_repository(repo_url=repo_url, pr_number=int(pr_number), repo_full_name=str(repo))
                sandbox_path = str(sandbox.temp_path)
                span.add_event("repo_cloned", {"python_files": sandbox.python_files_indexed, "repo_size_bytes": sandbox.repo_size_bytes})

                # Initialize repository index for style retrieval using sandbox.
                initialize_repo_index(repo_path=sandbox_path)
                # Warm dependency graph cache (best-effort).
                try:
                    build_code_graph(sandbox_path)
                except Exception:
                    logger.warning("Failed to build code graph for repository %s", repo)
            except RepoSandboxError as exc:
                span.record_exception(exc)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

            repo_metadata: Dict[str, Any] = {
                "repository": repo,
                "pr_number": pr_number,
                "action": action,
                "pr_id": pr_id,
            }

            # Enqueue Celery tasks and wait for completion (tasks execute in parallel).
            await broker.broadcast(
                pr_id,
                {"type": "agent_started", "agent": "style", "pr_id": pr_id},
            )
            style_started = time.time()
            style_result = run_style_agent.delay(diff_text, repo_metadata)
            await broker.broadcast(
                pr_id,
                {"type": "agent_started", "agent": "logic", "pr_id": pr_id},
            )
            logic_started = time.time()
            logic_result = run_logic_agent.delay(diff_text, repo_metadata)
            await broker.broadcast(
                pr_id,
                {"type": "agent_started", "agent": "security", "pr_id": pr_id},
            )
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

            # Log agent executions and emit events/metrics.
            log_agent_execution(
                pr_id,
                "style",
                style_started,
                style_finished,
                style_output_dict,
                execution_duration=style_finished - style_started,
                agent_order=1,
            )
            AGENT_EXECUTION_TIME.labels("style").observe(style_finished - style_started)
            await broker.broadcast(
                pr_id,
                {
                    "type": "agent_finished",
                    "agent": "style",
                    "pr_id": pr_id,
                    "confidence": style_output.confidence,
                    "issue_count": len(style_output.issues),
                },
            )
            span.add_event("agent_finished", {"agent": "style", "confidence": float(style_output.confidence)})

            log_agent_execution(
                pr_id,
                "logic",
                logic_started,
                logic_finished,
                logic_output_dict,
                execution_duration=logic_finished - logic_started,
                agent_order=2,
            )
            AGENT_EXECUTION_TIME.labels("logic").observe(logic_finished - logic_started)
            await broker.broadcast(
                pr_id,
                {
                    "type": "agent_finished",
                    "agent": "logic",
                    "pr_id": pr_id,
                    "confidence": logic_output.confidence,
                    "issue_count": len(logic_output.issues),
                },
            )
            span.add_event("agent_finished", {"agent": "logic", "confidence": float(logic_output.confidence)})

            log_agent_execution(
                pr_id,
                "security",
                security_started,
                security_finished,
                security_output_dict,
                execution_duration=security_finished - security_started,
                agent_order=3,
            )
            AGENT_EXECUTION_TIME.labels("security").observe(security_finished - security_started)
            await broker.broadcast(
                pr_id,
                {
                    "type": "agent_finished",
                    "agent": "security",
                    "pr_id": pr_id,
                    "confidence": security_output.confidence,
                    "issue_count": len(security_output.issues),
                },
            )
            span.add_event("agent_finished", {"agent": "security", "confidence": float(security_output.confidence)})

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
            TOTAL_PRS_PROCESSED.inc()
            REVIEW_CONFIDENCE.observe(float(arb_output.get("overall_confidence", 0.0)))
            await broker.broadcast(
                pr_id,
                {
                    "type": "confidence_updated",
                    "pr_id": pr_id,
                    "overall_confidence": arb_output.get("overall_confidence", 0.0),
                },
            )
            span.add_event("arbitrator_complete", {"overall_confidence": float(arb_output.get("overall_confidence", 0.0))})

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
        finally:
            if sandbox_path:
                cleanup_repository(sandbox_path)


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


@app.websocket("/stream/{pr_id}")
async def stream_events(websocket: WebSocket, pr_id: str) -> None:
    """
    WebSocket endpoint for live event streaming for a given PR ID.
    """
    await broker.register(pr_id, websocket)
    try:
        while True:
            # We don't expect messages from the client, but need to keep the connection alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broker.unregister(pr_id, websocket)


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    """
    Prometheus metrics endpoint.
    """
    data = generate_latest()
    return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


__all__ = ["app"]

