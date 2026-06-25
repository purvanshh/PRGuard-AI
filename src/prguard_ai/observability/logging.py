"""Execution logging utilities for PRGuard AI using SQLAlchemy."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import select

from prguard_ai.db.session import async_session
from prguard_ai.db.models import AgentLog, LLMUsage


async def log_agent_execution(
    pr_id: str,
    agent: str,
    started_at: float,
    finished_at: float,
    output: Dict[str, Any],
    token_usage: int | None = None,
    execution_duration: float | None = None,
    agent_order: int | None = None,
) -> None:
    """Log the execution of an analysis agent asynchronously in PostgreSQL."""
    duration = execution_duration
    if duration is None:
        duration = max(0.0, float(finished_at - started_at))

    async with async_session() as session:
        async with session.begin():
            log = AgentLog(
                pr_id=str(pr_id),
                agent=agent,
                started_at=started_at,
                finished_at=finished_at,
                confidence=float(output.get("confidence", 0.0)),
                token_usage=int(token_usage or 0),
                execution_duration=float(duration),
                agent_order=int(agent_order or 0),
                payload=json.dumps(output),
            )
            session.add(log)


async def log_llm_usage(
    pr_id: str,
    agent: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: float,
) -> None:
    """Log token usage and cost for an LLM call asynchronously in PostgreSQL."""
    async with async_session() as session:
        async with session.begin():
            usage = LLMUsage(
                pr_id=str(pr_id),
                agent=agent,
                model=model,
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                estimated_cost_usd=float(estimated_cost_usd),
            )
            session.add(usage)


async def fetch_pr_logs(pr_id: str) -> List[Dict[str, Any]]:
    """Retrieve all execution logs for a given PR ID from PostgreSQL."""
    async with async_session() as session:
        stmt = select(AgentLog).where(AgentLog.pr_id == str(pr_id)).order_by(AgentLog.started_at)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    logs: List[Dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(row.payload)
        except json.JSONDecodeError:
            parsed = {}
        logs.append(
            {
                "agent": row.agent,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "confidence": row.confidence,
                "token_usage": row.token_usage,
                "execution_duration": row.execution_duration,
                "agent_order": row.agent_order,
                "output": parsed,
            }
        )
    return logs


__all__ = ["log_agent_execution", "log_llm_usage", "fetch_pr_logs"]
