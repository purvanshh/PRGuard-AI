"""Semgrep integration glue for PRGuard AI agents.

Runs Semgrep against the repository sandbox and emits results as a fourth
agent-style output that feeds the Confidence Arbitrator alongside the
Style/Logic/Security LLM agents.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from prguard_ai.config.feature_flags import is_enabled, rollout_enabled
from prguard_ai.config.settings import settings
from prguard_ai.semgrep.parser import SemgrepFinding, findings_to_issues
from prguard_ai.semgrep.scanner import SemgrepScanner

logger = logging.getLogger(__name__)

MAX_SEMGREP_ISSUES = 50


def _in_testing() -> bool:
    return os.getenv("PRGUARD_TESTING") == "true" or "PYTEST_CURRENT_TEST" in os.environ


def _should_persist() -> bool:
    return settings.semgrep_persist_logs and not _in_testing()


def log_semgrep_run(
    pr_id: str,
    output: Any,
    findings: List[SemgrepFinding],
    started_at: float,
    duration: float,
) -> None:
    """Best-effort persistence of a Semgrep run to ``agent_logs``.

    Wired for the dynamic-weight feedback loop: the payload records the
    findings count and the set of rules that fired so historical FP rates can
    be derived. Never raises — a failed DB write is logged and swallowed.
    """
    if not pr_id or not _should_persist():
        return
    try:
        from prguard_ai.db.session import run_async
        from prguard_ai.observability.logging import log_agent_execution

        payload = output.model_dump() if hasattr(output, "model_dump") else dict(output)
        payload["findings_count"] = len(findings)
        payload["rules_used"] = sorted({f.rule_id for f in findings})
        run_async(
            log_agent_execution(
                pr_id=str(pr_id),
                agent="semgrep",
                started_at=float(started_at),
                finished_at=float(started_at + duration),
                output=payload,
                execution_duration=float(duration),
                agent_order=3,
            )
        )
    except Exception:
        logger.warning("Failed to persist Semgrep run for %s", pr_id, exc_info=True)


def semgrep_enabled_for(repo: str = "") -> bool:
    """Feature-gated rollout check for the Semgrep integration."""
    if not is_enabled("semgrep_integration", default=False):
        return False
    return rollout_enabled("semgrep_integration", repo, default_percent=100.0)


def _load_scanner() -> SemgrepScanner:
    configs = [c.strip() for c in settings.semgrep_configs.split(",") if c.strip()]
    if not configs:
        configs = ["p/owasp-top-ten"]
    return SemgrepScanner(
        binary=settings.semgrep_binary,
        configs=configs,
        timeout_seconds=settings.semgrep_timeout_seconds,
        max_target_bytes=settings.semgrep_max_target_bytes,
    )


def _diff_changed_files(diff_text: str) -> set[str]:
    from prguard_ai.analysis.diff_parser import extract_changed_files

    try:
        return {path.lstrip("/") for path in extract_changed_files(diff_text)}
    except Exception:
        logger.warning("Failed to extract changed files from diff; scanning all findings", exc_info=True)
        return set()


def _filter_to_changed_files(findings: List[SemgrepFinding], changed: set[str]) -> List[SemgrepFinding]:
    if not changed:
        return findings
    return [f for f in findings if f.file_path in changed]


def _apply_dynamic_weights(issues: List[Any]) -> None:
    """Demote noisy Semgrep rules based on historical false-positive rates.

    Resolves each rule's effective weight through the configured feedback
    provider (PostgreSQL-backed in production) and stores the result as a
    per-issue ``source_weight_override`` so confidence scoring honors it.
    """
    if not issues:
        return
    from prguard_ai.semgrep.weights import DEFAULT_SEMGREP_WEIGHT, DynamicSemgrepWeight, get_db_feedback_provider

    resolver = DynamicSemgrepWeight(provider=get_db_feedback_provider())
    cache: dict[str, float] = {}
    for issue in issues:
        if issue.confidence_source != "semgrep" or not issue.rule_id:
            continue
        if issue.rule_id not in cache:
            cache[issue.rule_id] = resolver.weight_for(issue.rule_id)
        effective = cache[issue.rule_id]
        if effective != DEFAULT_SEMGREP_WEIGHT:
            issue.source_weight_override = effective


def run_semgrep_scan(diff_text: str, repo_metadata: Dict[str, Any] | None = None):
    """Run Semgrep against the sandbox clone and return an AgentOutput."""
    from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
    from prguard_ai.schemas.agent_output import AgentOutput

    meta = repo_metadata or {}
    repo = meta.get("repository", "unknown")
    sandbox_path = meta.get("sandbox_path")

    reasoning_trace: List[str] = []
    if not semgrep_enabled_for(repo):
        reasoning_trace.append("semgrep: integration disabled via feature flag")
        return AgentOutput(agent="semgrep", confidence=0.0, llm_skipped=True, reasoning_trace=reasoning_trace)

    if not sandbox_path or not Path(str(sandbox_path)).is_dir():
        reasoning_trace.append("semgrep: sandbox unavailable; scan skipped")
        return AgentOutput(agent="semgrep", confidence=0.0, llm_skipped=True, reasoning_trace=reasoning_trace)

    scanner = _load_scanner()
    target = Path(str(sandbox_path))
    baseline_ref = settings.semgrep_baseline_ref
    started_at = time.time()
    findings = scanner.scan(target, baseline_ref=baseline_ref)
    duration = time.time() - started_at

    reasoning_trace.append(
        f"semgrep: scanned {target} with configs={scanner.configs} baseline={baseline_ref or 'none'}"
    )
    if not findings:
        reasoning_trace.append("semgrep: no findings")
        output = AgentOutput(agent="semgrep", confidence=0.55, reasoning_trace=reasoning_trace)
        log_semgrep_run(meta.get("pr_id"), output, findings, started_at, duration)
        return output

    findings = _filter_to_changed_files(findings, _diff_changed_files(diff_text))
    findings = findings[:MAX_SEMGREP_ISSUES]
    issues = findings_to_issues(findings)
    _apply_dynamic_weights(issues)

    reasoning_trace.append(f"semgrep: found {len(issues)} issue(s) in the diff")
    confidence = estimate_issue_confidence(issues, empty_confidence=0.55)
    output = AgentOutput(
        agent="semgrep",
        confidence=confidence,
        issues=issues,
        llm_skipped=True,
        reasoning_trace=reasoning_trace,
    )
    log_semgrep_run(meta.get("pr_id"), output, findings, started_at, duration)
    return output


__all__ = ["run_semgrep_scan", "semgrep_enabled_for"]
