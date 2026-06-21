"""FastAPI-powered GitHub webhook server for PRGuard AI."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from prguard_ai.config.settings import settings
from prguard_ai.analysis.repo_indexer import initialize_repo_index
from prguard_ai.analysis.code_graph import build_code_graph
from prguard_ai.analysis.repo_sandbox import RepoSandboxError, cleanup_repository, clone_repository
from prguard_ai.gh_client.github_client import (
    format_pr_review,
    get_pr_diff,
    post_pr_comment,
    post_inline_comment,
)
from prguard_ai.observability.logging import fetch_pr_logs, log_agent_execution, _get_conn as _get_db_conn  # type: ignore
from prguard_ai.observability.event_stream import broker
from prguard_ai.observability.metrics import (
    TOTAL_PRS_PROCESSED,
    AGENT_EXECUTION_TIME,
    REVIEW_CONFIDENCE,
)
from prguard_ai.observability.tracing import get_tracer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi.responses import PlainTextResponse
from prguard_ai.task_queue.celery_app import (
    run_arbitrator,
    run_logic_agent,
    run_security_agent,
    run_style_agent,
    review_pr,
)
from prguard_ai.task_queue.task_registry import (
    acquire_global_slot,
    complete_pr_processing,
    is_pr_processing,
    register_pr_processing,
    release_global_slot,
)
from prguard_ai.security.rate_limiter import check_installation_limit, check_repo_limit
from prguard_ai.task_queue.redis_client import get_redis
from prguard_ai.schemas.agent_output import AgentOutput

logger = logging.getLogger(__name__)
_TRACER = get_tracer("webhook")

app = FastAPI(title="PRGuard AI Webhook Server", version="0.1.0")


_REPO_FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DELIVERY_ID_PATTERN = re.compile(r"^[A-Fa-f0-9-]{8,128}$")


def _validate_repo_full_name(raw: object) -> str:
    if not isinstance(raw, str) or not _REPO_FULL_NAME_PATTERN.fullmatch(raw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_repository", "reason": "Repository full name is malformed."},
        )
    return raw


def _validate_pr_number(raw: object) -> int:
    try:
        pr_number = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_pr_number", "reason": "Pull request number must be an integer."},
        ) from exc
    if pr_number <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_pr_number", "reason": "Pull request number must be positive."},
        )
    return pr_number


def _validate_repo_url_from_payload(payload: dict) -> str:
    repo_url = payload.get("repository", {}).get("clone_url") or payload.get("repository", {}).get("html_url")
    if not repo_url or not isinstance(repo_url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_repo_url", "reason": "Clone URL missing from webhook payload."},
        )
    return repo_url


def _validate_delivery_id(raw: object) -> str:
    if not isinstance(raw, str) or not _DELIVERY_ID_PATTERN.fullmatch(raw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_delivery_id", "reason": "X-GitHub-Delivery must be a UUID-like token."},
        )
    return raw


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


def check_redis() -> str:
    """Return 'connected' if Redis is reachable, otherwise 'disconnected'."""
    try:
        get_redis().ping()
        return "connected"
    except Exception:
        return "disconnected"


def check_database() -> str:
    """Return 'connected' if the database is reachable, otherwise 'disconnected'."""
    try:
        conn = _get_db_conn()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return "connected"
    except Exception:
        return "disconnected"


def check_openai() -> str:
    """Return 'configured' if OpenAI API key is set, otherwise 'missing'."""
    return "configured" if bool(settings.openai_api_key) else "missing"


def check_queue_depth() -> Dict[str, int]:
    """Return queue depths for Celery queues."""
    r = get_redis()
    queues = ["style", "logic", "security", "arbitrator"]
    depths: Dict[str, int] = {}
    for name in queues:
        try:
            depths[name] = int(r.llen(name))
        except Exception:
            depths[name] = -1
    return depths


@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_github_timestamp: str | None = Header(None, alias="X-GitHub-Timestamp"),
    raw_body: bytes = Depends(get_raw_body),
) -> Dict[str, Any]:
    """
    GitHub webhook endpoint.
    """
    # 1. Payload size limit (5MB).
    max_bytes = 5 * 1024 * 1024
    if len(raw_body) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": "payload_too_large", "reason": "Webhook payload exceeds 5MB limit."},
        )

    # 2. Replay protection using X-GitHub-Delivery as a unique ID.
    delivery_id = _validate_delivery_id(x_github_delivery)
    r = get_redis()
    delivery_key = f"prguard:webhook:delivery:{delivery_id}"
    if not r.setnx(delivery_key, "1"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "replay_detected", "reason": "Duplicate delivery ID received."},
        )
    # TTL 5 minutes.
    r.expire(delivery_key, 5 * 60)

    # 3. Timestamp validation (reject requests older than 2 minutes).
    if x_github_timestamp:
        try:
            ts = float(x_github_timestamp)
            now = time.time()
            age = now - ts
            if age > 120 or age < -120:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "stale_request",
                        "reason": "Webhook timestamp is outside the allowed window.",
                    },
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_timestamp", "reason": "X-GitHub-Timestamp must be a UNIX epoch seconds value."},
            )

    # 4. Signature verification.
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

    repo = _validate_repo_full_name(payload["repository"]["full_name"])
    pr_number = _validate_pr_number(payload["number"])
    pr_id = f"{repo}#{pr_number}"
    try:
        installation_id = int(payload.get("installation", {}).get("id", 0))
    except (TypeError, ValueError):
        installation_id = 0

    # Rate limiting per repo and installation.
    if not check_repo_limit(repo):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="repo rate limit exceeded",
        )
    if installation_id and not check_installation_limit(installation_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="installation rate limit exceeded",
        )

    # Idempotency: skip if already processing this PR.
    if is_pr_processing(pr_id):
        return {"status": "ignored", "reason": "already_processing"}

    # Global concurrency control.
    if not acquire_global_slot():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="backpressure",
        )

    with _TRACER.start_as_current_span("webhook_received") as span:
        span.set_attribute("pr.id", pr_id)
        span.set_attribute("repo.full_name", repo)
        span.set_attribute("pr.number", int(pr_number))
        span.set_attribute("pr.action", action or "")

        diff_text = get_pr_diff(repo_full_name=repo, pr_number=pr_number)

        sandbox_path: str | None = None
        # Track whether we successfully registered this PR for processing.
        registered = False
        try:
            # Attempt to register this PR as in-flight.
            registered = register_pr_processing(pr_id)
            if not registered:
                return {"status": "ignored", "reason": "already_processing"}
            try:
                repo_url = _validate_repo_url_from_payload(payload)
                sandbox = clone_repository(repo_url=repo_url, pr_number=pr_number, repo_full_name=str(repo))
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

            # Enqueue the orchestrator Celery task
            await broker.broadcast(
                pr_id,
                {"type": "agent_started", "agent": "orchestrator", "pr_id": pr_id},
            )
            orch_result = review_pr.delay(pr_id, diff_text, repo_metadata)
            arb_output = orch_result.get(timeout=600)

            # Log events/metrics
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
            span.add_event("orchestrator_complete", {"overall_confidence": float(arb_output.get("overall_confidence", 0.0))})

            return {"status": "ok", "overall_confidence": arb_output.get("overall_confidence", 0.0)}
        finally:
            if sandbox_path:
                cleanup_repository(sandbox_path)
            if registered:
                complete_pr_processing(pr_id)
            release_global_slot()


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
async def health() -> Dict[str, Any]:
    """
    Extended health check endpoint.
    """
    redis_status = check_redis()
    database_status = check_database()
    openai_status = check_openai()
    queue_depth = check_queue_depth()

    overall = "ok"
    if redis_status != "connected" or database_status != "connected" or openai_status != "configured":
        overall = "degraded"

    return {
        "status": overall,
        "redis": redis_status,
        "database": database_status,
        "openai": openai_status,
        "queue_depth": queue_depth,
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
