"""SQLAlchemy models for database logging in PRGuard AI."""

from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AgentLog(Base):
    """Logs detailing execution details of individual analysis agents."""

    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(String(255), nullable=False, index=True)
    agent = Column(String(100), nullable=False)
    started_at = Column(Float, nullable=False)
    finished_at = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    token_usage = Column(Integer, nullable=True)
    execution_duration = Column(Float, nullable=True)
    agent_order = Column(Integer, nullable=True)
    payload = Column(Text, nullable=False)  # JSON serialized dict representing agent output


class LLMUsage(Base):
    """Token usage and estimated cost stats for LLM invocations."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(String(255), nullable=False, index=True)
    agent = Column(String(100), nullable=False)
    model = Column(String(255), nullable=True)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    estimated_cost_usd = Column(Float, nullable=False)


# ORM model aliases to satisfy system terminology requirements
AuditLog = AgentLog
TokenUsage = LLMUsage

__all__ = ["Base", "AgentLog", "LLMUsage", "AuditLog", "TokenUsage"]
