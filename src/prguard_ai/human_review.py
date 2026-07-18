"""Human-in-the-loop approval workflow for uncertain findings."""

from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Literal

from prguard_ai.schemas.agent_output import Issue
from prguard_ai.schemas.pr_report import PullRequestReport

Decision = Literal["approved", "rejected", "modified"]


@dataclass
class PendingHumanReview:
    review_id: str
    pr_id: str
    report: PullRequestReport
    reason: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    escalation_sent: bool = False


class HumanReviewQueue:
    def __init__(self, auto_post_threshold: float = 0.72) -> None:
        self.auto_post_threshold = auto_post_threshold
        self._pending: Dict[str, PendingHumanReview] = {}

    def should_auto_post(self, report: PullRequestReport) -> bool:
        if report.overall_confidence < self.auto_post_threshold:
            return False
        return all(issue.severity != "high" or report.overall_confidence >= 0.8 for issue in report.issues)

    def enqueue(self, pr_id: str, report: PullRequestReport, reason: str = "low_confidence") -> PendingHumanReview:
        seed = f"{pr_id}:{time.time_ns()}".encode("utf-8")
        review_id = hashlib.sha256(seed).hexdigest()[:16]
        pending = PendingHumanReview(review_id=review_id, pr_id=pr_id, report=report, reason=reason)
        self._pending[review_id] = pending
        return pending

    def list_pending(self) -> list[PendingHumanReview]:
        return [item for item in self._pending.values() if item.status == "pending"]

    def decide(self, review_id: str, decision: Decision, override_message: str | None = None) -> PendingHumanReview:
        pending = self._pending[review_id]
        pending.status = decision
        if decision == "modified" and override_message:
            pending.report.issues = [
                Issue(
                    line=1,
                    severity="medium",
                    message=override_message,
                    evidence="Human reviewer override",
                    confidence_source="human_feedback",
                )
            ]
        return pending


def escalation_message(pending: PendingHumanReview) -> str:
    """Build a Slack/email-friendly escalation message."""
    pending.escalation_sent = True
    return (
        f"PRGuard needs review for {pending.pr_id}: {pending.reason}. "
        f"Confidence={pending.report.overall_confidence:.2f}, findings={len(pending.report.issues)}"
    )


human_review_queue = HumanReviewQueue()

__all__ = [
    "Decision",
    "HumanReviewQueue",
    "PendingHumanReview",
    "escalation_message",
    "human_review_queue",
]
