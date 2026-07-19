"""Confidence scoring engine for PRGuard AI."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Iterable, Dict, Sequence

from prguard_ai.schemas.agent_output import AgentOutput, Issue


DEFAULT_CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "rule_based": 0.9,
    "llm_reasoning": 0.6,
    "refined": 0.7,
    "inferred": 0.3,
}
SEVERITY_CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "low": 0.45,
    "medium": 0.65,
    "high": 0.85,
}
LEARNED_CONFIDENCE_WEIGHTS: Dict[str, float] = dict(DEFAULT_CONFIDENCE_WEIGHTS)


@dataclass(frozen=True)
class CalibratedConfidence:
    """Calibrated probability plus a Wilson 95% confidence interval."""

    probability: float
    lower: float
    upper: float
    sample_count: int

    @property
    def margin(self) -> float:
        return round(max(self.probability - self.lower, self.upper - self.probability), 4)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def fit_platt_scaling(
    samples: Sequence[tuple[float, int]],
    *,
    iterations: int = 400,
    learning_rate: float = 0.05,
) -> tuple[float, float]:
    """Fit a tiny logistic calibration model from human feedback samples."""
    if not samples:
        return 1.0, 0.0

    slope = 1.0
    intercept = 0.0
    prepared = [(_clamp(score), 1 if label else 0) for score, label in samples]
    for _ in range(iterations):
        grad_slope = 0.0
        grad_intercept = 0.0
        for score, label in prepared:
            pred = _sigmoid(slope * score + intercept)
            error = pred - label
            grad_slope += error * score
            grad_intercept += error
        count = float(len(prepared))
        slope -= learning_rate * grad_slope / count
        intercept -= learning_rate * grad_intercept / count
    return round(slope, 6), round(intercept, 6)


def calibrate_confidence(
    raw_score: float,
    *,
    samples: Sequence[tuple[float, int]] | None = None,
    slope: float | None = None,
    intercept: float | None = None,
) -> float:
    """Convert a raw score into an empirically calibrated probability."""
    if samples:
        slope, intercept = fit_platt_scaling(samples)
    if slope is None:
        slope = 1.0
    if intercept is None:
        intercept = 0.0
    return round(_clamp(_sigmoid(slope * _clamp(raw_score) + intercept)), 4)


def confidence_interval(probability: float, sample_count: int, confidence: float = 0.95) -> tuple[float, float]:
    """Return a Wilson score interval for calibrated finding correctness."""
    probability = _clamp(probability)
    if sample_count <= 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    n = float(sample_count)
    denominator = 1 + z * z / n
    center = (probability + z * z / (2 * n)) / denominator
    spread = z * math.sqrt((probability * (1 - probability) + z * z / (4 * n)) / n) / denominator
    return round(_clamp(center - spread), 4), round(_clamp(center + spread), 4)


def calibrated_confidence(
    raw_score: float,
    *,
    sample_count: int = 0,
    samples: Sequence[tuple[float, int]] | None = None,
    slope: float | None = None,
    intercept: float | None = None,
) -> CalibratedConfidence:
    probability = calibrate_confidence(raw_score, samples=samples, slope=slope, intercept=intercept)
    if samples is not None:
        sample_count = len(samples)
    lower, upper = confidence_interval(probability, sample_count)
    return CalibratedConfidence(probability, lower, upper, sample_count)


def _weight_for_source(source: str) -> float:
    """Return a numeric weight for a confidence source label."""
    return LEARNED_CONFIDENCE_WEIGHTS.get(source, LEARNED_CONFIDENCE_WEIGHTS["inferred"])


def update_learned_weights(feedback: Iterable[tuple[str, int]]) -> Dict[str, float]:
    """Update source weights from human finding feedback."""
    grouped: Dict[str, list[int]] = {}
    for source, accepted in feedback:
        grouped.setdefault(source, []).append(1 if accepted else 0)
    for source, labels in grouped.items():
        if labels:
            LEARNED_CONFIDENCE_WEIGHTS[source] = round(_clamp(sum(labels) / len(labels)), 4)
    return dict(LEARNED_CONFIDENCE_WEIGHTS)


def estimate_issue_confidence(
    issues: Iterable[Issue],
    *,
    empty_confidence: float,
    max_issue_bonus: float = 0.09,
) -> float:
    """
    Estimate an agent confidence directly from the detected issues.

    This keeps base agent confidence aligned with the quality of the findings
    before the arbitrator applies its own cross-agent refinement.
    """
    issues_list = list(issues)
    if not issues_list:
        return max(0.0, min(1.0, empty_confidence))

    combined_scores = []
    for issue in issues_list:
        source_score = _weight_for_source(issue.confidence_source)
        severity_score = SEVERITY_CONFIDENCE_WEIGHTS.get(
            issue.severity.lower(),
            SEVERITY_CONFIDENCE_WEIGHTS["low"],
        )
        combined_scores.append((source_score + severity_score) / 2.0)

    avg_score = sum(combined_scores) / len(combined_scores)
    issue_bonus = min(len(issues_list), 3) * (max_issue_bonus / 3.0)
    return max(0.0, min(1.0, avg_score + issue_bonus))


def calculate_agent_confidence(output: AgentOutput) -> float:
    """
    Calculate a refined confidence score for a single agent output.

    The base agent confidence is adjusted according to the mix of confidence sources
    in its issues using the configured weights.
    """
    if not output.issues:
        return output.confidence

    total_weight = 0.0
    for issue in output.issues:
        total_weight += _weight_for_source(issue.confidence_source)

    avg_weight = total_weight / max(len(output.issues), 1)
    # Blend the original confidence with the average weight.
    refined = (output.confidence + avg_weight) / 2.0
    return max(0.0, min(1.0, refined))


def aggregate_confidence(outputs: Iterable[AgentOutput]) -> float:
    """
    Aggregate confidence across agents into a single score.

    Each agent's refined confidence is averaged, with additional influence from
    the highest-severity issues.
    """
    outputs_list = list(outputs)
    if not outputs_list:
        return 0.0

    refined_scores = [calculate_agent_confidence(o) for o in outputs_list]
    base_avg = sum(refined_scores) / len(refined_scores)

    # Boost slightly if any high-severity issues exist.
    has_high_severity = any(
        issue.severity.lower() == "high" for o in outputs_list for issue in o.issues
    )
    if has_high_severity:
        base_avg = min(1.0, base_avg + 0.1)

    return base_avg


def aggregate_calibrated_confidence(
    outputs: Iterable[AgentOutput],
    *,
    sample_count: int = 0,
    slope: float | None = None,
    intercept: float | None = None,
) -> CalibratedConfidence:
    return calibrated_confidence(
        aggregate_confidence(outputs),
        sample_count=sample_count,
        slope=slope,
        intercept=intercept,
    )


__all__ = [
    "CalibratedConfidence",
    "calculate_agent_confidence",
    "aggregate_confidence",
    "aggregate_calibrated_confidence",
    "calibrate_confidence",
    "calibrated_confidence",
    "confidence_interval",
    "estimate_issue_confidence",
    "fit_platt_scaling",
    "update_learned_weights",
]
