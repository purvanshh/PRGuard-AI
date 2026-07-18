"""Online feedback collection, calibration, A/B routing, and shadow runs."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Iterable

from prguard_ai.schemas.agent_output import Issue


def finding_key(pr_id: str, issue: Issue) -> str:
    raw = f"{pr_id}|{issue.file_path or ''}|{issue.line}|{issue.severity}|{issue.message}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def reaction_to_score(content: str) -> float | None:
    if content in {"+1", "heart", "hooray"}:
        return 1.0
    if content in {"-1", "confused"}:
        return 0.0
    return None


@dataclass(frozen=True)
class FeedbackSignal:
    finding_key: str
    pr_id: str
    source: str
    signal: str
    score: float
    actor: str | None
    created_at: float


class FeedbackCollector:
    """Collect GitHub reactions from PRGuard review comments."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def collect_reactions(self, repo_full_name: str, pr_number: int, comment_to_finding: dict[int, str]) -> list[FeedbackSignal]:
        from prguard_ai.gh_client.github_client import _get_github_client

        gh = _get_github_client(self.token)
        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        pr_id = f"{repo_full_name}#{pr_number}"
        signals: list[FeedbackSignal] = []
        for comment in list(pr.get_issue_comments()) + list(pr.get_review_comments()):
            key = comment_to_finding.get(int(comment.id))
            if not key:
                continue
            for reaction in comment.get_reactions():
                score = reaction_to_score(str(reaction.content))
                if score is None:
                    continue
                actor = getattr(getattr(reaction, "user", None), "login", None)
                created_at = getattr(reaction, "created_at", None)
                signals.append(
                    FeedbackSignal(
                        finding_key=key,
                        pr_id=pr_id,
                        source="github_reaction",
                        signal=str(reaction.content),
                        score=score,
                        actor=actor,
                        created_at=created_at.timestamp() if created_at else time.time(),
                    )
                )
        return signals


def recalibrate_confidence(samples: Iterable[tuple[float, float]]) -> tuple[float, float]:
    """Fit a tiny logistic calibration curve from (confidence, accepted) samples."""
    rows = [(max(0.001, min(0.999, c)), 1.0 if y >= 0.5 else 0.0) for c, y in samples]
    if len(rows) < 2:
        return 1.0, 0.0
    slope = 1.0
    intercept = 0.0
    learning_rate = 0.2
    for _ in range(200):
        grad_slope = 0.0
        grad_intercept = 0.0
        for confidence, accepted in rows:
            logit = math.log(confidence / (1.0 - confidence))
            pred = 1.0 / (1.0 + math.exp(-(slope * logit + intercept)))
            error = pred - accepted
            grad_slope += error * logit
            grad_intercept += error
        slope -= learning_rate * grad_slope / len(rows)
        intercept -= learning_rate * grad_intercept / len(rows)
    return slope, intercept


def assign_variant(subject: str, *, experiment: str, rollout: float = 0.10, control: str = "current", treatment: str = "candidate") -> str:
    """Deterministically route a subject into control/treatment."""
    rollout = max(0.0, min(1.0, rollout))
    digest = hashlib.sha256(f"{experiment}:{subject}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return treatment if bucket < rollout else control


def should_shadow_run(pr_id: str, enabled: bool = True) -> bool:
    return enabled and assign_variant(pr_id, experiment="shadow_model", rollout=1.0) == "candidate"


def serialize_shadow_findings(findings: list[Issue] | list[dict[str, Any]]) -> str:
    payload = [item.model_dump() if isinstance(item, Issue) else item for item in findings]
    return json.dumps(payload, sort_keys=True)


__all__ = [
    "FeedbackCollector",
    "FeedbackSignal",
    "assign_variant",
    "finding_key",
    "reaction_to_score",
    "recalibrate_confidence",
    "serialize_shadow_findings",
    "should_shadow_run",
]
