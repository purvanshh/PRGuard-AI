"""Policy parsing and enforcement for per-repository PRGuard rules."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field, field_validator

from prguard_ai.analysis.diff_parser import DiffHunk, parse_diff
from prguard_ai.schemas.agent_output import Issue

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
ORDERED_SEVERITIES = ["low", "medium", "high", "critical"]


class PolicyConfig(BaseModel):
    """Validated `.prguard.yml` policy."""

    severity_threshold: str = Field(default="low")
    ignored_paths: list[str] = Field(default_factory=list)
    required_reviewers: list[str] = Field(default_factory=list)
    critical_paths: list[str] = Field(default_factory=list)
    severity_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("severity_threshold")
    @classmethod
    def _validate_threshold(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in SEVERITY_ORDER:
            raise ValueError(f"Unsupported severity threshold: {value}")
        return normalized

    @field_validator("severity_overrides")
    @classmethod
    def _validate_overrides(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for pattern, severity in value.items():
            severity_name = str(severity).lower()
            if severity_name not in SEVERITY_ORDER:
                raise ValueError(f"Unsupported severity override for {pattern}: {severity}")
            normalized[str(pattern)] = severity_name
        return normalized

    def is_ignored(self, path: str | None) -> bool:
        if not path:
            return False
        return any(_matches_path(path, pattern) for pattern in self.ignored_paths)

    def override_for_path(self, path: str | None) -> str | None:
        if not path:
            return None
        best: str | None = None
        for pattern, severity in self.severity_overrides.items():
            if _matches_path(path, pattern):
                best = severity
        if any(_matches_path(path, pattern) for pattern in self.critical_paths):
            best = "critical"
        return best


def _matches_path(path: str, pattern: str) -> bool:
    normalized_path = path.strip("/")
    normalized_pattern = pattern.strip("/")
    if fnmatch.fnmatch(normalized_path, normalized_pattern):
        return True
    if normalized_pattern.endswith("/**"):
        return normalized_path.startswith(normalized_pattern[:-3].rstrip("/") + "/")
    if normalized_pattern.endswith("/"):
        return normalized_path.startswith(normalized_pattern)
    return False


def _parse_scalar(raw: str) -> Any:
    value = raw.strip().strip("'\"")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def _parse_inline_list(raw: str) -> list[str]:
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    return [item.strip().strip("'\"") for item in stripped.split(",") if item.strip()]


def parse_policy_text(text: str) -> PolicyConfig:
    """Parse a constrained YAML subset used by `.prguard.yml`."""
    data: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if not value:
                data[current_key] = {}
            elif value.startswith("["):
                data[current_key] = _parse_inline_list(value)
                current_key = None
            else:
                data[current_key] = _parse_scalar(value)
                current_key = None
            continue
        if current_key is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            existing = data.get(current_key)
            if not isinstance(existing, list):
                existing = []
                data[current_key] = existing
            existing.append(_parse_scalar(stripped[2:]))
        elif ":" in stripped:
            nested_key, nested_value = stripped.split(":", 1)
            existing = data.get(current_key)
            if not isinstance(existing, dict):
                existing = {}
                data[current_key] = existing
            existing[nested_key.strip().strip("'\"")] = _parse_scalar(nested_value)

    return PolicyConfig.model_validate(data)


def load_policy_file(path: Path) -> PolicyConfig:
    if not path.exists():
        return PolicyConfig()
    return parse_policy_text(path.read_text(encoding="utf-8"))


def merge_policies(org_policy: PolicyConfig | Mapping[str, Any] | None, repo_policy: PolicyConfig | Mapping[str, Any] | None) -> PolicyConfig:
    """Merge org defaults with repo overrides."""
    org = _coerce_policy(org_policy)
    repo = _coerce_policy(repo_policy)
    merged = org.model_dump()
    repo_data = repo.model_dump()
    for key, value in repo_data.items():
        default_value = PolicyConfig().model_dump()[key]
        if value != default_value:
            merged[key] = value
    return PolicyConfig.model_validate(merged)


def _coerce_policy(value: PolicyConfig | Mapping[str, Any] | None) -> PolicyConfig:
    if isinstance(value, PolicyConfig):
        return value
    if isinstance(value, Mapping):
        return PolicyConfig.model_validate(value)
    return PolicyConfig()


def load_effective_policy(repo_metadata: Mapping[str, Any] | None) -> PolicyConfig:
    metadata = repo_metadata or {}
    org_policy = _coerce_policy(metadata.get("org_policy"))
    inline_policy = metadata.get("policy")
    if inline_policy:
        return merge_policies(org_policy, _coerce_policy(inline_policy))

    sandbox_path = metadata.get("sandbox_path")
    repo_policy = PolicyConfig()
    if sandbox_path:
        repo_policy = load_policy_file(Path(str(sandbox_path)) / ".prguard.yml")
    return merge_policies(org_policy, repo_policy)


def filter_diff_by_policy(diff_text: str, policy: PolicyConfig) -> str:
    """Remove ignored files from a unified diff before agent analysis."""
    parsed = parse_diff(diff_text)
    ignored = {path for path in parsed if policy.is_ignored(path)}
    if not ignored:
        return diff_text

    chunks: list[list[str]] = []
    current: list[str] = []
    current_path: str | None = None
    keep_current = True
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current and keep_current:
                chunks.append(current)
            current = [line]
            current_path = None
            keep_current = True
            continue
        if line.startswith("+++ "):
            current_path = line[4:].strip()
            if current_path.startswith(("a/", "b/")):
                current_path = current_path[2:]
            keep_current = current_path not in ignored
        current.append(line)
    if current and keep_current:
        chunks.append(current)
    return "\n".join("\n".join(chunk) for chunk in chunks)


def apply_policy_to_issues(issues: list[Issue], policy: PolicyConfig) -> list[Issue]:
    """Filter ignored findings, apply severity thresholds, and elevate critical paths."""
    filtered: list[Issue] = []
    threshold_rank = SEVERITY_ORDER[policy.severity_threshold]
    for issue in issues:
        if policy.is_ignored(issue.file_path):
            continue
        override = policy.override_for_path(issue.file_path)
        if override and SEVERITY_ORDER[override] > SEVERITY_ORDER.get(issue.severity, 0):
            issue = issue.model_copy(update={"severity": override})
        if SEVERITY_ORDER.get(issue.severity, 0) < threshold_rank:
            continue
        filtered.append(issue)
    return filtered


__all__ = [
    "PolicyConfig",
    "apply_policy_to_issues",
    "filter_diff_by_policy",
    "load_effective_policy",
    "load_policy_file",
    "merge_policies",
    "parse_policy_text",
]
