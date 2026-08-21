"""Semgrep static analysis integration for PRGuard AI."""

from prguard_ai.semgrep.agent import run_semgrep_scan, semgrep_enabled_for
from prguard_ai.semgrep.autofix import apply_semgrep_autofix, push_autofix_commit
from prguard_ai.semgrep.parser import SemgrepFinding, findings_to_issues, parse_semgrep_json
from prguard_ai.semgrep.scanner import SemgrepScanner
from prguard_ai.semgrep.weights import (
    DEFAULT_SEMGREP_WEIGHT,
    DynamicSemgrepWeight,
    MemoryFeedbackProvider,
    NoopFeedbackProvider,
    RuleFeedbackProvider,
    compute_effective_weight,
)

__all__ = [
    "DEFAULT_SEMGREP_WEIGHT",
    "DynamicSemgrepWeight",
    "MemoryFeedbackProvider",
    "NoopFeedbackProvider",
    "RuleFeedbackProvider",
    "SemgrepFinding",
    "SemgrepScanner",
    "apply_semgrep_autofix",
    "compute_effective_weight",
    "findings_to_issues",
    "parse_semgrep_json",
    "push_autofix_commit",
    "run_semgrep_scan",
    "semgrep_enabled_for",
]
