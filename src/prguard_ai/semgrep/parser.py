"""Parsing of Semgrep JSON output into PRGuard-compatible findings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass(frozen=True)
class SemgrepFinding:
    """A single normalized Semgrep finding mapped to PRGuard severity levels."""

    rule_id: str
    severity: str  # low | medium | high
    message: str
    file_path: str
    line: int
    evidence: str
    category: Optional[str] = None
    cwe: List[str] = field(default_factory=list)
    owasp: List[str] = field(default_factory=list)


SEVERITY_MAP = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
}


def _normalize_severity(raw: Any, default: str = "medium") -> str:
    mapped = SEVERITY_MAP.get(str(raw).upper(), "")
    return mapped or default


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _result_to_finding(result: dict) -> Optional[SemgrepFinding]:
    if result.get("extra", {}).get("is_ignored"):
        return None

    check_id = str(result.get("check_id") or "unknown-rule")

    start = result.get("start") or {}
    line = int(start.get("line", 1) or 1)
    if line < 1:
        line = 1

    extra = result.get("extra") or {}
    metadata = extra.get("metadata") or {}
    evidence = str(extra.get("lines") or "").strip()

    return SemgrepFinding(
        rule_id=check_id,
        severity=_normalize_severity(extra.get("severity")),
        message=str(extra.get("message") or check_id).strip()[:500],
        file_path=str(result.get("path") or "").lstrip("/"),
        line=line,
        evidence=evidence[:400],
        category=str(metadata.get("category") or "") or None,
        cwe=_string_list(metadata.get("cwe")),
        owasp=_string_list(metadata.get("owasp")),
    )


def parse_semgrep_json(raw: str) -> List[SemgrepFinding]:
    """Parse the JSON contract emitted by `semgrep scan --json`.

    Accepts both the top-level object form (``{"results": [...]}``) and a
    bare list of results. Findings suppressed via ``nosemgrep`` comments are
    marked ``is_ignored`` by Semgrep and filtered out here.
    """
    data = json.loads(raw)
    results: List[dict] = []
    if isinstance(data, dict):
        results = data.get("results", [])
    elif isinstance(data, list):
        results = data

    findings: List[SemgrepFinding] = []
    for result in results:
        finding = _result_to_finding(result)
        if finding:
            findings.append(finding)
    return findings


def findings_to_issues(findings: List[SemgrepFinding]) -> Any:
    """Convert parsed findings into PRGuard Issue objects (lazy import)."""
    from prguard_ai.schemas.agent_output import Issue

    issues = []
    for finding in findings:
        issues.append(
            Issue(
                line=finding.line,
                severity=finding.severity,
                message=f"[semgrep/{finding.rule_id}] {finding.message}",
                evidence=finding.evidence or f"{finding.file_path}:{finding.line}",
                confidence_source="semgrep",
                file_path=finding.file_path or None,
                verified=True,
            )
        )
    return issues


__all__ = ["SemgrepFinding", "findings_to_issues", "parse_semgrep_json"]
