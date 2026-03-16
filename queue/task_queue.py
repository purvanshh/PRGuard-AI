"""Celery task queue configuration and task definitions for PRGuard AI."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from celery import Celery

from agents.arbitrator_agent import arbitrate_confidence
from agents.logic_agent import analyze_logic
from agents.security_agent import analyze_security
from agents.style_agent import analyze_style
from config.settings import settings
from schemas.agent_output import AgentOutput
from schemas.pr_report import PullRequestReport


CELERY_BROKER_URL = settings.redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_BACKEND_URL = CELERY_BROKER_URL

celery_app = Celery("prguard_ai", broker=CELERY_BROKER_URL, backend=CELERY_BACKEND_URL)
celery_app.conf.task_routes = {
    "queue.task_queue.run_style_agent": {"queue": "style"},
    "queue.task_queue.run_logic_agent": {"queue": "logic"},
    "queue.task_queue.run_security_agent": {"queue": "security"},
    "queue.task_queue.run_arbitrator": {"queue": "arbitrator"},
}
celery_app.conf.task_time_limit = 60
celery_app.conf.task_soft_time_limit = 45


@celery_app.task(name="queue.task_queue.run_style_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_style_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the style analysis agent."""
    output: AgentOutput = analyze_style(diff_text, repo_metadata=repo_metadata or {})
    return output.dict()


@celery_app.task(name="queue.task_queue.run_logic_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_logic_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the logic analysis agent."""
    output: AgentOutput = analyze_logic(diff_text, repo_metadata=repo_metadata or {})
    return output.dict()


@celery_app.task(name="queue.task_queue.run_security_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_security_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the security analysis agent."""
    output: AgentOutput = analyze_security(diff_text, repo_metadata=repo_metadata or {})
    return output.dict()


@celery_app.task(name="queue.task_queue.run_arbitrator")
def run_arbitrator(agent_outputs: List[Dict[str, Any]]) -> dict:
    """Celery task that runs the confidence arbitrator."""
    outputs: List[AgentOutput] = [AgentOutput(**o) for o in agent_outputs]
    report: PullRequestReport = arbitrate_confidence(outputs)
    data = report.dict()
    disagreements = getattr(report, "disagreements", [])
    data["disagreements"] = disagreements
    return data


__all__ = [
    "celery_app",
    "run_style_agent",
    "run_logic_agent",
    "run_security_agent",
    "run_arbitrator",
]

