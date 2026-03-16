"""Security analysis agent for PRGuard AI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from analysis.diff_parser import DiffHunk, parse_diff
from llm.client import generate_analysis
from schemas.agent_output import AgentOutput, Issue

PROMPT_PATH = Path("prompts/security_prompt.txt")
MAX_FILES_PER_PR = 50
MAX_TOKENS_PER_AGENT = 2000


SUSPECT_KEYWORDS = ["eval(", "exec(", "subprocess.Popen", "os.system"]


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a code review assistant focusing on SECURITY. "
        "Respond with a JSON array of issues."
    )


def detect_sql_injection(line: str) -> bool:
    patterns = ["SELECT ", "INSERT ", "UPDATE ", "DELETE "]
    return any(p in line and (" + " in line or f"{p}\"" in line or f"{p}'" in line) for p in patterns)


def detect_eval_usage(line: str) -> bool:
    return "eval(" in line or "exec(" in line


def detect_hardcoded_secrets(line: str) -> bool:
    lowered = line.lower()
    if "api_key" in lowered or "secret" in lowered or "token" in lowered:
        if any(ch.isdigit() for ch in line) and any(ch.isalpha() for ch in line) and len(line.strip()) > 20:
            return True
    return False


def _parse_llm_issues(raw: str) -> List[Issue]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: List[Issue] = []
    for item in data:
        try:
            out.append(
                Issue(
                    line=int(item.get("line", 1)),
                    severity=str(item.get("severity", "high")),
                    message=str(item.get("message", "")),
                    evidence=str(item.get("evidence", "")),
                    confidence_source=str(item.get("confidence_source", "llm_reasoning")),
                )
            )
        except Exception:
            continue
    return out


def analyze_security(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Detect security vulnerabilities using both rule-based checks and LLM reasoning.
    """
    repo_metadata = repo_metadata or {}
    parsed = parse_diff(diff_text)

    files = list(parsed.keys())[:MAX_FILES_PER_PR]
    file_hunks: List[DiffHunk] = []
    for f in files:
        file_hunks.extend(parsed[f])

    issues: List[Issue] = []
    for h in file_hunks:
        for line in h.lines:
            if line.line_type != "add":
                continue
            text = line.content
            lineno = line.new_lineno or 1

            if detect_eval_usage(text):
                issues.append(
                    Issue(
                        line=lineno,
                        severity="high",
                        message="Use of eval/exec detected; this is often unsafe.",
                        evidence=text[:200],
                        confidence_source="rule_based",
                    )
                )
            if detect_sql_injection(text):
                issues.append(
                    Issue(
                        line=lineno,
                        severity="high",
                        message="Potential SQL injection pattern (string-concatenated query).",
                        evidence=text[:200],
                        confidence_source="rule_based",
                    )
                )
            if detect_hardcoded_secrets(text):
                issues.append(
                    Issue(
                        line=lineno,
                        severity="high",
                        message="Possible hardcoded secret or API key.",
                        evidence=text[:200],
                        confidence_source="rule_based",
                    )
                )

    llm_issues: List[Issue] = []
    if diff_text:
        prompt = _load_prompt() + "\n\n--- Diff ---\n" + diff_text
        text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT)
        llm_issues = _parse_llm_issues(text)

    all_issues = issues + llm_issues
    confidence = 0.95 if all_issues else 0.6
    return AgentOutput(agent="security", confidence=confidence, issues=all_issues)


__all__ = [
    "analyze_security",
    "detect_sql_injection",
    "detect_eval_usage",
    "detect_hardcoded_secrets",
]

