"""Logic analysis agent for PRGuard AI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from prguard_ai.analysis.ast_parser import AstSummary, summarize_source
from prguard_ai.analysis.diff_parser import DiffHunk, extract_context_lines, parse_diff
from prguard_ai.llm.client import generate_analysis
from prguard_ai.schemas.agent_output import AgentOutput, Issue

PROMPT_PATH = Path("prompts/logic_prompt.txt")
MAX_FILES_PER_PR = 50
MAX_TOKENS_PER_AGENT = 2000


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a code review assistant focusing on LOGICAL CORRECTNESS. "
        "Respond with a JSON array of issues."
    )


def _build_ast_summary_for_hunks(hunks: List[DiffHunk]) -> AstSummary | None:
    added_code_lines: List[str] = []
    for h in hunks:
        for line in h.lines:
            if line.line_type == "add" and line.content.strip():
                added_code_lines.append(line.content)
    if not added_code_lines:
        return None
    snippet = "\n".join(added_code_lines)
    return summarize_source(snippet)


def _build_llm_input(
    diff_text: str,
    context_snippets: List[str],
    ast_summary: AstSummary | None,
) -> str:
    base_prompt = _load_prompt()
    ctx = "\n\n".join(context_snippets[:5])
    ast_blob = ""
    if ast_summary is not None:
        ast_blob = json.dumps(
            {
                "functions": ast_summary.functions,
                "variables": ast_summary.variables,
                "control_structures": ast_summary.control_structures,
            },
            indent=2,
        )
    return (
        f"{base_prompt}\n\n"
        f"--- Changed code (Git diff) ---\n{diff_text}\n\n"
        f"--- Surrounding context ---\n{ctx}\n\n"
        f"--- AST summary of changed code ---\n{ast_blob}\n"
    )


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
                    severity=str(item.get("severity", "medium")),
                    message=str(item.get("message", "")),
                    evidence=str(item.get("evidence", "")),
                    confidence_source=str(item.get("confidence_source", "llm_reasoning")),
                )
            )
        except Exception:
            continue
    return out


def analyze_logic(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """
    Detect logical issues, edge cases, and potential runtime errors in the diff.
    """
    repo_metadata = repo_metadata or {}
    pr_id = repo_metadata.get("pr_id")
    parsed = parse_diff(diff_text)

    files = list(parsed.keys())[:MAX_FILES_PER_PR]
    file_hunks: List[DiffHunk] = []
    for f in files:
        file_hunks.extend(parsed[f])

    # Collect textual context around the first few hunks.
    context_snippets: List[str] = []
    for h in file_hunks[:5]:
        if h.lines:
            first_add = next((l for l in h.lines if l.new_lineno is not None), None)
            if first_add is not None and first_add.new_lineno is not None:
                ctx = extract_context_lines(h.file_path, first_add.new_lineno, window=10)
                if ctx:
                    context_snippets.append(
                        f"# {h.file_path}:{first_add.new_lineno}\n" + "\n".join(ctx[:40])
                    )

    ast_summary = _build_ast_summary_for_hunks(file_hunks)

    # Simple static checks for TODOs and obvious runtime hazards.
    issues: List[Issue] = []
    for h in file_hunks:
        for line in h.lines:
            if line.line_type != "add":
                continue
            text = line.content
            if "TODO" in text:
                issues.append(
                    Issue(
                        line=line.new_lineno or 1,
                        severity="low",
                        message="TODO present in newly added code.",
                        evidence=text[:200],
                        confidence_source="inferred",
                        file_path=h.file_path,
                    )
                )
            if "except:" in text:
                issues.append(
                    Issue(
                        line=line.new_lineno or 1,
                        severity="medium",
                        message="Bare except detected; this can hide runtime errors.",
                        evidence=text[:200],
                        confidence_source="rule_based",
                        file_path=h.file_path,
                    )
                )

    # LLM reasoning.
    llm_issues: List[Issue] = []
    if diff_text:
        prompt = _build_llm_input(diff_text, context_snippets, ast_summary)
        text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
        llm_issues = _parse_llm_issues(text)

    all_issues = issues + llm_issues
    confidence = 0.9 if all_issues else 0.5
    return AgentOutput(agent="logic", confidence=confidence, issues=all_issues)


__all__ = ["analyze_logic"]

