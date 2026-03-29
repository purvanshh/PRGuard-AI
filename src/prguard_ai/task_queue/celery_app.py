"""Celery task queue configuration and task definitions for PRGuard AI."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from celery import Celery

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.config.settings import settings
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.pr_report import PullRequestReport
from prguard_ai.observability.tracing import get_tracer


_REDIS_MODE = os.getenv("REDIS_MODE", "single").lower()
_EAGER_MODE = os.getenv("CELERY_EAGER", "").lower() in {"1", "true", "yes", "on"}
if _REDIS_MODE == "memory":
    _EAGER_MODE = True

CELERY_BROKER_URL = settings.redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_BACKEND_URL = CELERY_BROKER_URL
if _EAGER_MODE:
    CELERY_BROKER_URL = "memory://"
    CELERY_BACKEND_URL = "cache+memory://"

celery_app = Celery("prguard_ai", broker=CELERY_BROKER_URL, backend=CELERY_BACKEND_URL)
celery_app.conf.task_routes = {
    "task_queue.celery_app.run_style_agent": {"queue": "style"},
    "task_queue.celery_app.run_logic_agent": {"queue": "logic"},
    "task_queue.celery_app.run_security_agent": {"queue": "security"},
    "task_queue.celery_app.run_arbitrator": {"queue": "arbitrator"},
}
celery_app.conf.task_time_limit = 60
celery_app.conf.task_soft_time_limit = 45

if _EAGER_MODE:
    # When Redis is unavailable (e.g., local dev without Docker), run tasks synchronously.
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True

_TRACER = get_tracer("celery")


@celery_app.task(name="task_queue.celery_app.run_style_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_style_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the style analysis agent."""
    with _TRACER.start_as_current_span("agent_style") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        output: AgentOutput = analyze_style(diff_text, repo_metadata=meta)
        return output.dict()


@celery_app.task(name="task_queue.celery_app.run_logic_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_logic_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the logic analysis agent."""
    with _TRACER.start_as_current_span("agent_logic") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        output: AgentOutput = analyze_logic(diff_text, repo_metadata=meta)
        return output.dict()


@celery_app.task(name="task_queue.celery_app.run_security_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_security_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the security analysis agent."""
    with _TRACER.start_as_current_span("agent_security") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        output: AgentOutput = analyze_security(diff_text, repo_metadata=meta)
        return output.dict()


@celery_app.task(name="task_queue.celery_app.run_arbitrator")
def run_arbitrator(agent_outputs: List[Dict[str, Any]]) -> dict:
    """Celery task that runs the confidence arbitrator."""
    with _TRACER.start_as_current_span("arbitrator") as span:
        outputs: List[AgentOutput] = [AgentOutput(**o) for o in agent_outputs]
        report: PullRequestReport = arbitrate_confidence(outputs)
        data = report.dict()
        disagreements = getattr(report, "disagreements", [])
        data["disagreements"] = disagreements
        if data.get("pr_id"):
            span.set_attribute("pr.id", data.get("pr_id"))
        span.set_attribute("review.overall_confidence", float(data.get("overall_confidence", 0.0)))
        return data


__all__ = [
    "celery_app",
    "run_style_agent",
    "run_logic_agent",
    "run_security_agent",
    "run_arbitrator",
]
