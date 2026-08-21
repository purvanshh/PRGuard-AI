"""Dynamic confidence weight adjustment for noisy Semgrep rules.

Semgrep rules that produce many false positives should contribute less to the
overall review confidence. This module computes an effective source weight
from historical developer feedback (findings ignored via ``nosemgrep``,
manual dismiss, or GitHub reactions).

The feedback provider is a pluggable interface. The default provider returns
no data, which means rules keep their full weight until a provider is wired to
a PostgreSQL-backed feedback store.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Protocol

from prguard_ai.confidence.scoring_engine import SOURCE_WEIGHTS

logger = logging.getLogger(__name__)

DEFAULT_SEMGREP_WEIGHT = SOURCE_WEIGHTS["semgrep"]  # 0.9
REDUCED_SEMGREP_WEIGHT = 0.6
SAMPLE_THRESHOLD = 10
MAX_FP_RATE = 0.3
LOOKBACK_DAYS = 30


def compute_effective_weight(
    rule_id: str,
    total_findings: int,
    ignored_findings: int,
    *,
    base_weight: float = DEFAULT_SEMGREP_WEIGHT,
    sample_threshold: int = SAMPLE_THRESHOLD,
    max_fp_rate: float = MAX_FP_RATE,
    reduced_weight: float = REDUCED_SEMGREP_WEIGHT,
) -> float:
    """Return the effective weight for a Semgrep rule based on its FP rate.

    Rules with fewer than ``sample_threshold`` recorded findings keep their
    base weight (insufficient evidence). Rules whose ignored/false-positive
    ratio exceeds ``max_fp_rate`` are down-weighted to ``reduced_weight``.
    """
    if total_findings <= 0:
        return base_weight
    if total_findings < sample_threshold:
        return base_weight

    ignored_findings = max(0, min(ignored_findings, total_findings))
    fp_rate = ignored_findings / total_findings
    if fp_rate > max_fp_rate:
        logger.info(
            "Reducing weight for semgrep rule %s: fp_rate=%.2f > %.2f (weight %s -> %s)",
            rule_id,
            fp_rate,
            max_fp_rate,
            base_weight,
            reduced_weight,
        )
        return reduced_weight
    return base_weight


class RuleFeedbackProvider(Protocol):
    """Provider of per-rule false-positive statistics."""

    def ignored_counts(self, rule_id: str, days: int = LOOKBACK_DAYS) -> Optional[tuple[int, int]]:
        """Return ``(total_findings, ignored_findings)`` for a rule, or None."""
        ...


class NoopFeedbackProvider:
    """Default provider: no feedback data yet, so full weight is kept."""

    def ignored_counts(self, rule_id: str, days: int = LOOKBACK_DAYS) -> Optional[tuple[int, int]]:
        return None


class DynamicSemgrepWeight:
    """Resolves effective weights per rule, delegating feedback to a provider."""

    def __init__(self, provider: RuleFeedbackProvider | None = None) -> None:
        self.provider = provider or NoopFeedbackProvider()

    def weight_for(self, rule_id: str) -> float:
        counts = self.provider.ignored_counts(rule_id)
        if counts is None:
            return DEFAULT_SEMGREP_WEIGHT
        total, ignored = counts
        return compute_effective_weight(rule_id, total, ignored)


class MemoryFeedbackProvider:
    """In-memory feedback provider useful for tests and demos."""

    def __init__(self, counts: dict[str, tuple[int, int]]) -> None:
        self.counts = counts

    def ignored_counts(self, rule_id: str, days: int = LOOKBACK_DAYS) -> Optional[tuple[int, int]]:
        return self.counts.get(rule_id)


class DatabaseFeedbackProvider:
    """Production provider: reads ignored-finding counts from PostgreSQL.

    Findings are correlated to Semgrep rules via the ``[semgrep/<rule-id>]``
    message prefix in the ``findings`` table; "ignored" is derived from
    ``online_feedback`` (dismiss/reject/thumbsdown) and ``human_feedback``
    (reject) signals. Best-effort: returns ``None`` (keeping the default 0.9
    weight) when the database is unreachable or no feedback has been recorded.
    """

    IGNORED_SIGNALS = ("dismiss", "ignore", "reject", "thumbsdown")

    def __init__(self, days: int = LOOKBACK_DAYS) -> None:
        self.days = int(days)

    def ignored_counts(self, rule_id: str, days: int = LOOKBACK_DAYS) -> Optional[tuple[int, int]]:
        import os

        if os.getenv("PRGUARD_TESTING") == "true" or "PYTEST_CURRENT_TEST" in os.environ:
            return None
        try:
            from prguard_ai.db.session import run_async

            return run_async(self._query(rule_id, days or self.days))
        except Exception:
            logger.warning("Semgrep feedback query failed for rule %s", rule_id, exc_info=True)
            return None

    async def _query(self, rule_id: str, days: int) -> Optional[tuple[int, int]]:
        import time

        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from prguard_ai.config.settings import settings
        from prguard_ai.db.models import FindingRecord, HumanFeedback, OnlineFeedback

        url = settings.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Dedicated engine per query avoids async loop-binding issues when the
        # shared engine is used from sync Celery contexts.
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                cutoff = time.time() - int(days) * 86400
                pattern = f"[semgrep/{rule_id}]%"
                total = (
                    await session.execute(
                        select(func.count())
                        .select_from(FindingRecord)
                        .where(FindingRecord.message.like(pattern), FindingRecord.created_at >= cutoff)
                    )
                ).scalar() or 0
                if not total:
                    return None
                online_ignored = (
                    await session.execute(
                        select(func.count())
                        .select_from(FindingRecord)
                        .join(OnlineFeedback, OnlineFeedback.finding_key == FindingRecord.finding_key)
                        .where(
                            FindingRecord.message.like(pattern),
                            FindingRecord.created_at >= cutoff,
                            OnlineFeedback.signal.in_(self.IGNORED_SIGNALS),
                        )
                    )
                ).scalar() or 0
                human_ignored = (
                    await session.execute(
                        select(func.count())
                        .select_from(FindingRecord)
                        .join(HumanFeedback, HumanFeedback.finding_key == FindingRecord.finding_key)
                        .where(
                            FindingRecord.message.like(pattern),
                            FindingRecord.created_at >= cutoff,
                            HumanFeedback.decision == "reject",
                        )
                    )
                ).scalar() or 0
                return int(total), int(online_ignored) + int(human_ignored)
        finally:
            await engine.dispose()


def get_db_feedback_provider() -> RuleFeedbackProvider:
    """Return the production feedback provider wired to PostgreSQL."""
    return DatabaseFeedbackProvider()


__all__ = [
    "DEFAULT_SEMGREP_WEIGHT",
    "DatabaseFeedbackProvider",
    "DynamicSemgrepWeight",
    "MemoryFeedbackProvider",
    "NoopFeedbackProvider",
    "RuleFeedbackProvider",
    "compute_effective_weight",
    "get_db_feedback_provider",
]
