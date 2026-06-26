"""Comprehensive health check checkers for PRGuard AI."""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Dict

from sqlalchemy import text

from prguard_ai.config.settings import settings
from prguard_ai.db.session import async_session
from prguard_ai.task_queue.redis_client import get_redis


logger = logging.getLogger(__name__)


def check_redis() -> str:
    """Check Redis connectivity."""
    try:
        get_redis().ping()
        return "connected"
    except Exception as e:
        logger.warning("Health check: Redis is down: %s", e)
        return "disconnected"


async def check_postgres() -> str:
    """Check PostgreSQL connectivity."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return "connected"
    except Exception as e:
        logger.warning("Health check: PostgreSQL is down: %s", e)
        return "disconnected"


def check_llm() -> str:
    """Check LLM endpoint health (cached for 30s)."""
    from prguard_ai.llm.client import check_llm_health
    return check_llm_health()


def check_github() -> str:
    """Check GitHub API token/permissions availability."""
    try:
        from prguard_ai.gh_client.github_client import _get_github_client
        gh = _get_github_client()
        # Verify connectivity by getting rate limit (minimal request)
        gh.get_rate_limit()
        return "connected"
    except Exception as e:
        logger.warning("Health check: GitHub API is down: %s", e)
        return "disconnected"


def check_celery() -> str:
    """Check Celery worker status."""
    try:
        from prguard_ai.task_queue.celery_app import celery_app
        if getattr(celery_app.conf, "task_always_eager", False):
            return "eager_mode"
        inspector = celery_app.control.inspect()
        active = inspector.active()
        if active:
            return "active"
        return "no_active_workers"
    except Exception as e:
        logger.warning("Health check: Celery inspect failed: %s", e)
        return "disconnected"


def check_chromadb() -> str:
    """Check ChromaDB health (best-effort style retrieval query)."""
    try:
        from prguard_ai.analysis.repo_indexer import retrieve_similar_code
        # retrieve_similar_code returns an iterable
        list(retrieve_similar_code("ping"))
        return "healthy"
    except Exception as e:
        logger.warning("Health check: ChromaDB failed: %s", e)
        return "disconnected"


def check_disk_space() -> str:
    """Check available space on /tmp for repository cloning."""
    try:
        total, used, free = shutil.disk_usage("/tmp")
        free_gb = free / (1024**3)
        if free_gb < 1.0:
            return f"low_space ({free_gb:.2f} GB)"
        return "healthy"
    except Exception as e:
        logger.warning("Health check: Disk space check failed: %s", e)
        return "error"


def check_logging() -> str:
    """Verify logging configuration."""
    try:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if handler.formatter and handler.formatter.__class__.__name__ == "JsonLogFormatter":
                return "configured"
        return "not_configured"
    except Exception as e:
        logger.warning("Health check: Logging check failed: %s", e)
        return "error"


async def get_health_status() -> Dict[str, Any]:
    """Aggregate health checks for all dependencies."""
    from prguard_ai.analysis.repo_cache import get_cache_stats

    redis_status = check_redis()
    db_status = await check_postgres()
    llm_status = check_llm()
    github_status = check_github()
    celery_status = check_celery()
    chroma_status = check_chromadb()
    disk_status = check_disk_space()
    logging_status = check_logging()
    cache_stats = get_cache_stats()

    # Determine critical statuses
    critical_healthy = (
        redis_status == "connected"
        and db_status == "connected"
        and llm_status in ("connected", "offline", "configured")  # offline or configured count as healthy in dev/test
    )

    overall_status = "ok"
    if not critical_healthy:
        overall_status = "unhealthy"
    elif (
        celery_status == "no_active_workers"
        or celery_status == "disconnected"
        or chroma_status == "disconnected"
        or disk_status.startswith("low_space")
    ):
        overall_status = "degraded"

    return {
        "status": overall_status,
        "critical": {
            "redis": redis_status,
            "database": db_status,
            "llm": llm_status,
        },
        "non_critical": {
            "github": github_status,
            "celery": celery_status,
            "chromadb": chroma_status,
            "disk": disk_status,
            "logging": logging_status,
        },
        "cache_stats": cache_stats,
    }
