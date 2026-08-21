"""Logic analysis agent for PRGuard AI."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence

from prguard_ai.agents.base_agent import BaseAgent
from prguard_ai.agents.tools.tool_args import (
    ToolArgs,
    GetTypeInfoArgs,
    RunTestArgs,
    SymbolicExecuteArgs,
    SearchCodebaseArgs,
    CheckDeadCodeArgs,
    SemgrepScanArgs,
)
from prguard_ai.analysis.ast_parser import AstSummary, detect_language, summarize_source
from prguard_ai.analysis.diff_parser import DiffHunk, extract_context_lines, parse_diff
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
from prguard_ai.llm.client import generate_analysis, parse_agent_issues
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.security.prompt_injection import response_is_suspicious, wrap_diff

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "logic_prompt.txt"
MAX_FILES_PER_PR = settings.max_files_per_pr
MAX_TOKENS_PER_AGENT = 2000


def _load_prompt() -> str:
    from prguard_ai.prompts import load_prompt

    prompt, _version = load_prompt(
        "logic",
        fallback=(
            "You are a code review assistant focusing on LOGICAL CORRECTNESS. "
            "Respond with a JSON array of issues."
        ),
    )
    return prompt


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
    semgrep_findings: List[Dict[str, Any]] | None = None,
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
    prompt = (
        f"{base_prompt}\n\n"
        f"--- Changed code (Git diff) ---\n{wrap_diff(diff_text)}\n\n"
        f"--- Surrounding context ---\n{ctx}\n\n"
        f"--- AST summary of changed code ---\n{ast_blob}\n"
    )
    if semgrep_findings:
        prompt += (
            "\nAdditionally, a deterministic AST scanner (Semgrep) flagged the following issues in this PR: \n"
            + json.dumps(semgrep_findings, indent=2)[:4000]
            + "\n\nFor each Semgrep finding:\n"
            "1. If you AGREE it is a vulnerability, explain the root cause in your own words.\n"
            "2. If you DISAGREE (false positive), explain specifically why the code is safe despite the pattern match.\n"
            "Use this to refine your final severity assessment."
        )
    return prompt


def _resolve_context_file_path(file_path: str, sandbox_path: str | None) -> Path:
    candidate = Path(file_path)
    if candidate.is_absolute() or not sandbox_path:
        return candidate
    return Path(sandbox_path) / candidate


def _strip_markdown_fence(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    last_fence = stripped.rfind("```")
    if first_newline == -1 or last_fence <= first_newline:
        return stripped
    return stripped[first_newline + 1:last_fence].strip()


def _parse_llm_issues(raw: str) -> List[Issue]:
    try:
        return parse_agent_issues(raw)[:20]
    except Exception:
        logger.warning("Failed to parse structured LLM logic response. Raw: %s", raw[:500], exc_info=True)
        return []


class LogicAgent(BaseAgent):
    agent_name = "logic"
    empty_confidence = 0.45

    def analyze_tool_needs(self, diff_text: str, changed_files: List[str]) -> Sequence[ToolArgs]:
        from prguard_ai.semgrep.agent import semgrep_enabled_for

        needs: list[ToolArgs] = []
        if semgrep_enabled_for(self.repo_metadata.get("repository", "")):
            needs.append(SemgrepScanArgs())
        has_python = any(f.endswith(".py") for f in changed_files)
        if changed_files:
            needs.append(GetTypeInfoArgs(file_path=changed_files[0]))
        if has_python:
            needs.append(RunTestArgs(test_path="tests"))
            needs.append(SymbolicExecuteArgs(file_path=changed_files[0]))
            needs.append(CheckDeadCodeArgs(file_path=changed_files[0]))
            needs.append(SearchCodebaseArgs(query="error"))
        return needs[:3]

    def detect_suspicious_findings(self, issues: List[Issue], diff_text: str) -> List[str]:
        for issue in issues:
            msg = issue.message.lower()
            if any(t in msg for t in ["test", "failing", "crash", "exception"]):
                return ["run_test"]
            if any(t in msg for t in ["type", "return", "parameter", "argument"]):
                return ["get_type_info"]
            if any(t in msg for t in ["unreachable", "dead code", "after return"]):
                return ["check_dead_code"]
            if any(t in msg for t in ["branch", "path", "condition", "control flow"]):
                return ["symbolic_execute"]
        return []

    def synthesize_issues(self, diff_text: str, tool_outputs: Dict[str, Any]) -> List[Issue]:
        parsed = parse_diff(diff_text)
        sandbox_path = self.repo_metadata.get("sandbox_path")
        pr_id = self.repo_metadata.get("pr_id")

        files = list(parsed.keys())[:MAX_FILES_PER_PR]
        file_hunks: List[DiffHunk] = []
        for filename in files:
            file_hunks.extend(parsed[filename])

        context_snippets: List[str] = []
        for h in file_hunks[:5]:
            if h.lines:
                first_add = next((l for l in h.lines if l.new_lineno is not None), None)
                if first_add is not None and first_add.new_lineno is not None:
                    ctx_path = _resolve_context_file_path(h.file_path, sandbox_path)
                    ctx = extract_context_lines(ctx_path, first_add.new_lineno, window=10)
                    if ctx:
                        context_snippets.append(f"# {h.file_path}:{first_add.new_lineno}\n" + "\n".join(ctx[:40]))

        ast_summary = _build_ast_summary_for_hunks(file_hunks)
        type_info = tool_outputs.get("get_type_info")
        if isinstance(type_info, dict) and type_info.get("functions"):
            context_snippets.append("Type info:\n" + json.dumps(type_info["functions"][:5], indent=2))
        test_output = tool_outputs.get("run_test")
        if isinstance(test_output, dict) and test_output.get("returncode", 0) != 0:
            context_snippets.append("Test failures:\n" + (test_output.get("stdout") or test_output.get("stderr") or "")[:500])

        issues: List[Issue] = []
        for h in file_hunks:
            diff_lines: list[tuple[int, str]] = []
            all_text_lines: list[str] = []
            added_set: set[int] = set()
            seen: set[int] = set()
            for i, line_obj in enumerate(h.lines):
                if line_obj.line_type == "add" and line_obj.content.strip():
                    lineno = line_obj.new_lineno or 1
                    seen.add(lineno)
                    added_set.add(lineno)
                    diff_lines.append((lineno, line_obj.content))
                    all_text_lines.append(line_obj.content)
                elif line_obj.content.strip():
                    lineno = line_obj.new_lineno or (line_obj.old_lineno or 1)
                    if lineno not in seen:
                        seen.add(lineno)
                        diff_lines.append((lineno, line_obj.content))
                        all_text_lines.append(line_obj.content)

            from prguard_ai.analysis.detectors import DetectorRegistry
            full_text = " ".join(all_text_lines)
            issues.extend(DetectorRegistry.match_all("logic", diff_lines, h.file_path, full_text, frozenset(added_set)))

        llm_issues: List[Issue] = []
        if diff_text:
            from prguard_ai.reliability.circuit_breaker import CircuitBreakerError
            from prguard_ai.llm.client import TokenBudgetExceededError

            try:
                semgrep_findings = (tool_outputs.get("semgrep_scan") or {}).get("findings", [])
                prompt = _build_llm_input(diff_text, context_snippets, ast_summary, semgrep_findings=semgrep_findings)
                text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
                if response_is_suspicious(text, diff_text):
                    logger.warning("Logic agent: suspicious LLM response for PR %s — possible prompt injection", pr_id)
                    self.reasoning_trace.append("logic: flagged potential prompt injection for manual review")
                llm_issues = _parse_llm_issues(text)
                if semgrep_findings:
                    self.reasoning_trace.append(f"logic: provided {len(semgrep_findings)} Semgrep findings as LLM context")
                self.reasoning_trace.append("logic: synthesized LLM findings after AST and test/tool inspection")
            except (CircuitBreakerError, TokenBudgetExceededError) as exc:
                logger.warning("Logic agent LLM skipped (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
                self.llm_skipped = True
                self.reasoning_trace.append("logic: skipped LLM synthesis due to circuit breaker or budget limits")

        return issues + llm_issues

    def score_confidence(self, issues: List[Issue]) -> float:
        return estimate_issue_confidence(issues, empty_confidence=self.empty_confidence)

    @staticmethod
    def refine(initial_output: AgentOutput, context: ReviewContext) -> tuple[str, AgentOutput]:
        """Refine logic agent issues and generate a dialogue message based on context."""
        from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
        from prguard_ai.analysis.diff_parser import extract_changed_files

        refine_prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "logic_refine_prompt.txt"
        if refine_prompt_path.exists():
            refine_prompt_base = refine_prompt_path.read_text(encoding="utf-8")
        else:
            refine_prompt_base = (
                "You are a code review assistant focusing on LOGICAL CORRECTNESS refinement. "
                "Respond with a JSON object containing message and issues."
            )

        own_findings_str = json.dumps([issue.model_dump() for issue in initial_output.issues], indent=2)

        other_findings_list = []
        for name, output in context.agent_outputs.items():
            if name != "logic":
                other_findings_list.append(
                    f"Agent: {name}\nFindings:\n" + json.dumps([issue.model_dump() for issue in output.issues], indent=2)
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
            clean = _strip_markdown_fence(text)
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


def analyze_logic(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """Detect logical issues with tool-grounded context collection."""
    return LogicAgent(repo_metadata).run_react_loop(diff_text)


__all__ = ["analyze_logic", "LogicAgent"]
