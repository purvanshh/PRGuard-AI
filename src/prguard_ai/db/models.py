"""SQLAlchemy models for database logging in PRGuard AI."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
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


class HumanFeedback(Base):
    """Human accept/reject/modify decisions linked to a PR finding."""

    __tablename__ = "human_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(String(255), nullable=False, index=True)
    review_id = Column(String(255), nullable=False, index=True)
    finding_key = Column(String(255), nullable=True)
    decision = Column(String(50), nullable=False)
    original_message = Column(Text, nullable=True)
    override_message = Column(Text, nullable=True)
    created_at = Column(Float, nullable=False)


class FindingRecord(Base):
    """Normalized finding row used to correlate GitHub feedback and model runs."""

    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    finding_key = Column(String(255), nullable=False, unique=True, index=True)
    pr_id = Column(String(255), nullable=False, index=True)
    file_path = Column(String(500), nullable=True)
    line = Column(Integer, nullable=True)
    severity = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    posted_comment_id = Column(String(255), nullable=True, index=True)
    created_at = Column(Float, nullable=False)


class OnlineFeedback(Base):
    """GitHub reaction or human feedback linked to a finding."""

    __tablename__ = "online_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    finding_key = Column(String(255), nullable=False, index=True)
    pr_id = Column(String(255), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    signal = Column(String(50), nullable=False)
    score = Column(Float, nullable=False)
    actor = Column(String(255), nullable=True)
    created_at = Column(Float, nullable=False)


class ABTestAssignment(Base):
    """Stable experiment assignment for a repository or PR."""

    __tablename__ = "ab_test_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment = Column(String(255), nullable=False, index=True)
    subject = Column(String(255), nullable=False, index=True)
    variant = Column(String(100), nullable=False)
    assigned_at = Column(Float, nullable=False)


class ShadowRun(Base):
    """Silent model run stored for comparison without posting findings."""

    __tablename__ = "shadow_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(String(255), nullable=False, index=True)
    model_version = Column(String(255), nullable=False)
    findings_json = Column(Text, nullable=False)
    posted = Column(Boolean, nullable=False, default=False)
    created_at = Column(Float, nullable=False)


class CalibrationSnapshot(Base):
    """Confidence recalibration parameters derived from feedback."""

    __tablename__ = "calibration_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(255), nullable=False, index=True)
    slope = Column(Float, nullable=False)
    intercept = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)
    created_at = Column(Float, nullable=False)


# ORM model aliases to satisfy system terminology requirements
AuditLog = AgentLog
TokenUsage = LLMUsage

__all__ = [
    "Base",
    "AgentLog",
    "LLMUsage",
    "HumanFeedback",
    "FindingRecord",
    "OnlineFeedback",
    "ABTestAssignment",
    "ShadowRun",
    "CalibrationSnapshot",
    "AuditLog",
    "TokenUsage",
]
