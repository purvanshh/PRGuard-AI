"""Style analysis agent for PRGuard AI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from analysis.diff_parser import DiffHunk, extract_hunks, extract_changed_files, parse_diff
from analysis.repo_indexer import retrieve_similar_code
from llm.client import generate_analysis
from schemas.agent_output import AgentOutput, Issue

PROMPT_PATH = Path("prompts/style_prompt.txt")
MAX_FILES_PER_PR = 50
MAX_TOKENS_PER_AGENT = 1500


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a code review assistant focusing exclusively on STYLE and CONSISTENCY. "
        "Respond with a JSON array of issues."
    )


def _build_llm_input(diff_text: str, repo_examples: List[str]) -> str:
    base_prompt = _load_prompt()
    examples_blob = "\n\n".join(repo_examples[:3])
    return (
        f"{base_prompt}\n\n"
        f"--- Repository style examples (truncated) ---\n{examples_blob}\n\n"
        f"--- Diff ---\n{diff_text}\n"
    )


def _parse_llm_issues(raw: str) -> List[Issue]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    issues: List[Issue] = []
    if not isinstance(data, list):
        return []
    for item in data:
        try:
            issues.append(
                Issue(
                    line=int(item.get("line", 1)),
                    severity=str(item.get("severity", "low")),
                    message=str(item.get("message", "")),
                    evidence=str(item.get("evidence", "")),
                    confidence_source=str(item.get("confidence_source", "llm_reasoning")),
                )
            )
        except Exception:
            continue
    return issues


def analyze_style(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Analyze style issues in the diff using both simple rules and LLM guidance.
    """
    repo_metadata = repo_metadata or {}
    pr_id = repo_metadata.get("pr_id")

    parsed = parse_diff(diff_text)
    changed_files = extract_changed_files(parsed)[:MAX_FILES_PER_PR]
    relevant_hunks: List[DiffHunk] = []
    for f in changed_files:
        relevant_hunks.extend(parsed.get(f, []))

    # Simple rule-based style checks (indentation and long lines).
    issues: List[Issue] = []
    for hunk in relevant_hunks:
        for line in hunk.lines:
            if line.line_type != "add" or line.content.strip() == "":
                continue
            text = line.content
            if "\t" in text:
                issues.append(
                    Issue(
                        line=line.new_lineno or 1,
                        severity="medium",
                        message="Tab character used for indentation instead of spaces.",
                        evidence=text[:200],
                        confidence_source="rule_based",
                    )
                )
            if len(text) > 120:
                issues.append(
                    Issue(
                        line=line.new_lineno or 1,
                        severity="low",
                        message="Line exceeds 120 characters.",
                        evidence=text[:200],
                        confidence_source="rule_based",
                    )
                )

    # Retrieve repository style examples from the index (if present).
    repo_examples: List[str] = []
    for path, code in retrieve_similar_code("\n".join(h.header for h in relevant_hunks)):
        repo_examples.append(f"# {path}\n{code[:400]}")

    # LLM-based style reasoning with token budgeting.
    llm_issues: List[Issue] = []
    if diff_text:
        prompt = _build_llm_input(diff_text, repo_examples)
        text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
        llm_issues = _parse_llm_issues(text)

    all_issues = issues + llm_issues
    confidence = 0.9 if all_issues else 0.5
    return AgentOutput(agent="style", confidence=confidence, issues=all_issues)


__all__ = ["analyze_style"]

