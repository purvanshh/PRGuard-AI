"""Logic analysis agent for PRGuard AI."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from prguard_ai.analysis.ast_parser import AstSummary, detect_language, summarize_source
from prguard_ai.analysis.diff_parser import DiffHunk, extract_context_lines, parse_diff
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
from prguard_ai.llm.client import extract_json_from_llm_response, generate_analysis
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "logic_prompt.txt"
MAX_FILES_PER_PR = settings.max_files_per_pr
MAX_TOKENS_PER_AGENT = 2000


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a code review assistant focusing on LOGICAL CORRECTNESS. "
        "Respond with a JSON array of issues."
    )


def _build_ast_summary_for_hunks(hunks: List[DiffHunk]) -> AstSummary | None:
    added_code_by_file: dict[str, List[str]] = defaultdict(list)
    for h in hunks:
        if detect_language(h.file_path) is None:
            continue
        for line in h.lines:
            if line.line_type == "add" and line.content.strip():
                added_code_by_file[h.file_path].append(line.content)
    if not added_code_by_file:
        return None

    combined_functions: List[Dict[str, Any]] = []
    combined_variables: set[str] = set()
    combined_controls: List[Dict[str, Any]] = []
    languages: set[str] = set()

    for file_path, added_lines in added_code_by_file.items():
        summary = summarize_source("\n".join(added_lines), file_path=file_path)
        combined_functions.extend(summary.functions)
        combined_variables.update(summary.variables)
        combined_controls.extend(summary.control_structures)
        if summary.language:
            languages.add(summary.language)

    return AstSummary(
        functions=combined_functions,
        variables=sorted(combined_variables),
        control_structures=combined_controls,
        language=next(iter(languages)) if len(languages) == 1 else "mixed",
    )


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
                "language": ast_summary.language,
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
    clean = extract_json_from_llm_response(raw)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM logic response as JSON. Raw: %s", raw[:500])
        return []
    if not isinstance(data, list):
        logger.warning("LLM logic response is not a JSON array. Raw: %s", raw[:500])
        return []
    out: List[Issue] = []
    for item in data:
        if len(out) >= 20:
            logger.warning("Logic agent hit maximum issue limit (20). Skipping remaining issues.")
            break
        try:
            out.append(Issue.validate_and_sanitize(item))
        except Exception as exc:
            logger.warning(
                "Parsing failure: failed to validate Issue from item %s. Exception: %s. Raw LLM response (truncated): %s",
                item,
                exc,
                raw[:500],
                exc_info=True
            )
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
    llm_skipped = False
    if diff_text:
        from prguard_ai.reliability.circuit_breaker import CircuitBreakerError
        from prguard_ai.llm.client import TokenBudgetExceededError
        try:
            prompt = _build_llm_input(diff_text, context_snippets, ast_summary)
            text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
            llm_issues = _parse_llm_issues(text)
        except (CircuitBreakerError, TokenBudgetExceededError) as exc:
            logger.warning("Logic agent LLM skipped (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
            llm_skipped = True

    all_issues = issues + llm_issues
    confidence = estimate_issue_confidence(all_issues, empty_confidence=0.45)
    return AgentOutput(agent="logic", confidence=confidence, issues=all_issues, llm_skipped=llm_skipped)


class LogicAgent:
    @staticmethod
    def refine(initial_output: AgentOutput, context: ReviewContext) -> tuple[str, AgentOutput]:
        """Refine logic agent issues and generate a dialogue message based on context."""
        from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
        from prguard_ai.analysis.diff_parser import extract_changed_files
        from prguard_ai.llm.client import extract_json_obj_from_llm_response

        refine_prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "logic_refine_prompt.txt"
        if refine_prompt_path.exists():
            refine_prompt_base = refine_prompt_path.read_text(encoding="utf-8")
        else:
            refine_prompt_base = (
                "You are a code review assistant focusing on LOGICAL CORRECTNESS refinement. "
                "Respond with a JSON object containing message and issues."
            )

        own_findings_str = json.dumps([issue.dict() for issue in initial_output.issues], indent=2)

        other_findings_list = []
        for name, output in context.agent_outputs.items():
            if name != "logic":
                other_findings_list.append(
                    f"Agent: {name}\nFindings:\n" + json.dumps([issue.dict() for issue in output.issues], indent=2)
                )
        other_findings_str = "\n\n".join(other_findings_list)

        # Build dialogue history string
        dialogue_turns = []
        for turn in context.dialogue:
            dialogue_turns.append(f"[{turn.speaker}]: {turn.message}")
        dialogue_str = "\n".join(dialogue_turns)

        prompt = (
            f"{refine_prompt_base}\n\n"
            f"--- Git Diff ---\n{context.diff_text}\n\n"
            f"--- Your Initial Findings ---\n{own_findings_str}\n\n"
            f"--- Other Agents' Findings ---\n{other_findings_str}\n\n"
            f"--- Dialogue History ---\n{dialogue_str}\n"
        )

        pr_id = context.repo_metadata.get("pr_id") if context.repo_metadata else context.pr_id

        from prguard_ai.reliability.circuit_breaker import CircuitBreakerError
        from prguard_ai.llm.client import TokenBudgetExceededError
        try:
            text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)

            # Parse refined response
            clean = extract_json_obj_from_llm_response(text)
            message = ""
            refined_issues_data = []
            try:
                data = json.loads(clean)
                if isinstance(data, dict):
                    message = str(data.get("message") or "")
                    refined_issues_data = data.get("issues") or []
                elif isinstance(data, list):
                    refined_issues_data = data
            except Exception:
                logger.warning("Failed to parse refinement response as JSON. Raw: %s", text[:500])

            refined_issues: List[Issue] = []
            for item in refined_issues_data:
                if len(refined_issues) >= 20:
                    logger.warning("Logic agent refinement hit maximum issue limit (20). Skipping remaining issues.")
                    break
                try:
                    refined_issues.append(Issue.validate_and_sanitize(item))
                except Exception as exc:
                    logger.warning(
                        "Parsing failure: failed to validate refined Issue from item %s. Exception: %s. Raw LLM response (truncated): %s",
                        item,
                        exc,
                        text[:500],
                        exc_info=True
                    )
                    continue

            # For files that are checked, attach file path context back if LLM lost it
            relevant_files = extract_changed_files(context.diff_text)
            for issue in refined_issues:
                if not issue.file_path and relevant_files:
                    issue.file_path = relevant_files[0]

            initial_issues_map = {(issue.line, issue.message.lower()): issue for issue in initial_output.issues}
            final_issues = []
            for issue in refined_issues:
                key = (issue.line, issue.message.lower())
                if key in initial_issues_map:
                    issue.confidence_source = initial_issues_map[key].confidence_source
                else:
                    issue.confidence_source = "refined"
                final_issues.append(issue)

            confidence = estimate_issue_confidence(final_issues, empty_confidence=0.45)
            refined_output = AgentOutput(agent="logic", confidence=confidence, issues=final_issues)
        except (CircuitBreakerError, TokenBudgetExceededError) as exc:
            logger.warning("Logic agent LLM skipped in refine (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
            refined_output = initial_output.model_copy(update={"llm_skipped": True})
            message = "LLM refinement skipped due to circuit breaker or budget constraints."

        return message, refined_output


__all__ = ["analyze_logic", "LogicAgent"]
