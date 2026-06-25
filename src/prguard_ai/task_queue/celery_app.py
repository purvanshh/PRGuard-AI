"""Celery task queue configuration and task definitions for PRGuard AI."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

import logging
from celery import Celery

from prguard_ai.agents.arbitrator_agent import arbitrate_confidence
from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.config.settings import settings
from prguard_ai.schemas.agent_output import AgentOutput
from prguard_ai.schemas.pr_report import PullRequestReport
from prguard_ai.observability.tracing import get_tracer

logger = logging.getLogger(__name__)


_REDIS_MODE = settings.redis_mode.lower()
_EAGER_MODE = settings.celery_eager
if _REDIS_MODE == "memory":
    _EAGER_MODE = True

CELERY_BROKER_URL = settings.redis_url
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
    "task_queue.celery_app.refine_agent": {"queue": "refinement"},
    "task_queue.orchestrator.review_pr": {"queue": "orchestrator"},
    "task_queue.tasks.prepare_repository": {"queue": "orchestrator"},
    "task_queue.tasks.post_review": {"queue": "orchestrator"},
    "task_queue.tasks.on_task_failure": {"queue": "orchestrator"},
}
celery_app.conf.task_time_limit = 300
celery_app.conf.task_soft_time_limit = 240
# Don't use eager mode - let tasks run async normally

if _EAGER_MODE:
    # When Redis is unavailable (e.g., local dev without Docker), run tasks synchronously.
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True

_TRACER = get_tracer("celery")


@celery_app.task(
    name="task_queue.celery_app.run_style_agent",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 1},
    time_limit=300,
    soft_time_limit=240,
)
def run_style_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the style analysis agent."""
    with _TRACER.start_as_current_span("agent_style") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        try:
            output: AgentOutput = analyze_style(diff_text, repo_metadata=meta)
            return output.dict()
        except Exception as exc:
            logger.exception("Style agent task failed")
            return {
                "agent": "style",
                "confidence": 0.0,
                "issues": [],
                "llm_skipped": True,
                "error": str(exc),
            }


@celery_app.task(
    name="task_queue.celery_app.run_logic_agent",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 1},
    time_limit=300,
    soft_time_limit=240,
)
def run_logic_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the logic analysis agent."""
    with _TRACER.start_as_current_span("agent_logic") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        try:
            output: AgentOutput = analyze_logic(diff_text, repo_metadata=meta)
            return output.dict()
        except Exception as exc:
            logger.exception("Logic agent task failed")
            return {
                "agent": "logic",
                "confidence": 0.0,
                "issues": [],
                "llm_skipped": True,
                "error": str(exc),
            }


@celery_app.task(
    name="task_queue.celery_app.run_security_agent",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 1},
    time_limit=300,
    soft_time_limit=240,
)
def run_security_agent(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> dict:
    """Celery task that executes the security analysis agent."""
    with _TRACER.start_as_current_span("agent_security") as span:
        meta = repo_metadata or {}
        if meta.get("pr_id"):
            span.set_attribute("pr.id", meta.get("pr_id"))
        try:
            output: AgentOutput = analyze_security(diff_text, repo_metadata=meta)
            return output.dict()
        except Exception as exc:
            logger.exception("Security agent task failed")
            return {
                "agent": "security",
                "confidence": 0.0,
                "issues": [],
                "llm_skipped": True,
                "error": str(exc),
            }


@celery_app.task(
    name="task_queue.celery_app.run_arbitrator",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    time_limit=300,
    soft_time_limit=240,
)
def run_arbitrator(agent_outputs: List[Dict[str, Any]]) -> dict:
    """Celery task that runs the confidence arbitrator."""
    from prguard_ai.schemas.context import ReviewContext
    with _TRACER.start_as_current_span("arbitrator") as span:
        try:
            outputs: List[AgentOutput] = []
            for o in agent_outputs:
                try:
                    outputs.append(AgentOutput(**o))
                except Exception:
                    # If parsing agent output fails, skip or handle as error
                    pass
            context = ReviewContext(
                pr_id="dummy",
                diff_text="",
                agent_outputs={o.agent: o for o in outputs}
            )
            report = arbitrate_confidence(context, partial=True)
            data = report.dict()
            disagreements = getattr(report, "disagreements", [])
            data["disagreements"] = disagreements
            
            # If any of the agent outputs had an error, mark report as degraded
            if any(o.error for o in outputs):
                data["degraded"] = True
                
            if data.get("pr_id"):
                span.set_attribute("pr.id", data.get("pr_id"))
            span.set_attribute("review.overall_confidence", float(data.get("overall_confidence", 0.0)))
            return data
        except Exception as exc:
            logger.error("Arbitrator failed: %s. Returning degraded report.", exc)
            outputs_list = []
            issues = []
            for o in agent_outputs:
                try:
                    out = AgentOutput(**o)
                    outputs_list.append(out.dict())
                    issues.extend(out.issues)
                except Exception:
                    pass
            return {
                "overall_confidence": 0.0,
                "agent_outputs": outputs_list,
                "issues": issues,
                "disagreements": [],
                "degraded": True,
                "error": str(exc),
            }


@celery_app.task(
    name="task_queue.celery_app.refine_agent",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 1},
    time_limit=300,
    soft_time_limit=240,
)
def refine_agent(pr_id: str, agent_name: str) -> dict:
    """Celery task that executes an agent's refinement pass."""
    from prguard_ai.db.redis_client import get_review_context, store_review_context
    from prguard_ai.agents import get_agent_by_name
    from prguard_ai.schemas.agent_output import AgentOutput

    with _TRACER.start_as_current_span(f"refine_{agent_name}") as span:
        span.set_attribute("pr.id", pr_id)
        ctx = get_review_context(pr_id)
        if not ctx:
            raise ValueError(f"Context missing for PR {pr_id}")

        agent = get_agent_by_name(agent_name)
        initial = ctx.agent_outputs[agent_name]
        message, refined = agent.refine(initial, ctx)

        # Update context in Redis (best-effort write; orchestrator performs final consistent merge)
        ctx.agent_outputs[agent_name] = refined
        store_review_context(pr_id, ctx)
        return {
            "message": message,
            "refined_output": refined.dict()
        }


__all__ = [
    "celery_app",
    "run_style_agent",
    "run_logic_agent",
    "run_security_agent",
    "run_arbitrator",
    "refine_agent",
    "review_pr",
]

# Import orchestrator tasks to register them with Celery and avoid circular imports
from prguard_ai.task_queue.orchestrator import review_pr
import prguard_ai.task_queue.tasks
