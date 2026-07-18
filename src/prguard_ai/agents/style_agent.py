"""Style analysis agent for PRGuard AI."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from prguard_ai.agents.base_agent import BaseAgent
from prguard_ai.agents.tools.schemas import ToolInvocation
from prguard_ai.analysis.diff_parser import DiffHunk, extract_changed_files, parse_diff
from prguard_ai.analysis.repo_indexer import retrieve_similar_code
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
from prguard_ai.llm.client import extract_json_from_llm_response, generate_analysis
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "style_prompt.txt"
MAX_FILES_PER_PR = settings.max_files_per_pr
MAX_TOKENS_PER_AGENT = 1500
FRONTEND_EXTENSIONS = {".css", ".scss", ".sass", ".less", ".html", ".htm", ".jsx", ".tsx", ".vue"}
CSS_DECLARATION_RE = re.compile(
    r"(?P<prop>color|background(?:-color)?)\s*:\s*(?P<value>[^;]+)",
    re.IGNORECASE,
)
FONT_SIZE_PX_RE = re.compile(r"font-size\s*:\s*(?P<value>\d+(?:\.\d+)?)px\b", re.IGNORECASE)
FONT_SIZE_REL_RE = re.compile(r"font-size\s*:\s*(?P<value>\d+(?:\.\d+)?)(rem|em)\b", re.IGNORECASE)
OUTLINE_NONE_RE = re.compile(r"\boutline\s*:\s*(?:none|0)\b", re.IGNORECASE)
RGB_COLOR_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([0-9.]+))?\s*\)",
    re.IGNORECASE,
)
COLOR_KEYWORDS = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "gray": "#808080",
    "grey": "#808080",
}


def _load_prompt() -> str:
    from prguard_ai.prompts import load_prompt

    prompt, _version = load_prompt(
        "style",
        fallback=(
        "You are a code review assistant focusing exclusively on STYLE and CONSISTENCY. "
        "Respond with a JSON array of issues."
        ),
    )
    return prompt


def _build_llm_input(diff_text: str, repo_examples: List[str]) -> str:
    base_prompt = _load_prompt()
    examples_blob = "\n\n".join(repo_examples[:3])
    return (
        f"{base_prompt}\n\n"
        "Additional focus:\n"
        "- Frontend/UI design regressions that make the interface look broken or unreadable\n"
        "- Unreadable text contrast, tiny text, missing focus styles, and obviously inconsistent visual styling\n\n"
        f"--- Repository style examples (truncated) ---\n{examples_blob}\n\n"
        f"--- Diff ---\n{diff_text}\n"
    )


def _parse_llm_issues(raw: str) -> List[Issue]:
    clean = extract_json_from_llm_response(raw)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM style response as JSON. Raw: %s", raw[:500])
        return []
    issues: List[Issue] = []
    if not isinstance(data, list):
        logger.warning("LLM style response is not a JSON array. Raw: %s", raw[:500])
        return []
    for item in data:
        if len(issues) >= 20:
            logger.warning("Style agent hit maximum issue limit (20). Skipping remaining issues.")
            break
        try:
            issues.append(Issue.validate_and_sanitize(item))
        except Exception as exc:
            logger.warning(
                "Parsing failure: failed to validate Issue from item %s. Exception: %s. Raw LLM response (truncated): %s",
                item,
                exc,
                raw[:500],
                exc_info=True
            )
            continue
    return issues


def _looks_like_frontend_change(file_path: str, text: str) -> bool:
    if Path(file_path).suffix.lower() in FRONTEND_EXTENSIONS:
        return True
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("style=", "classname=", "background", "font-size", "color:", "<div", "<span", "<button")
    )


def _normalize_color(raw_value: str) -> str | None:
    value = raw_value.strip().lower().rstrip("}").rstrip(";")
    value = value.replace("!important", "").strip().strip("'\"")
    if not value:
        return None
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) == 3:
            return "#" + "".join(ch * 2 for ch in hex_value)
        if len(hex_value) >= 6:
            return "#" + hex_value[:6]
        return None
    if value in COLOR_KEYWORDS:
        return COLOR_KEYWORDS[value]
    rgb_match = RGB_COLOR_RE.fullmatch(value)
    if rgb_match:
        r, g, b = (max(0, min(255, int(component))) for component in rgb_match.groups()[:3])
        alpha = rgb_match.group(4)
        if alpha is not None and float(alpha) == 0:
            return None
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _detect_frontend_design_issues(hunk: DiffHunk) -> List[Issue]:
    issues: List[Issue] = []
    color_declarations: List[tuple[int, str, str]] = []
    background_declarations: List[tuple[int, str, str]] = []
    emitted_keys: set[tuple[int, str]] = set()

    for line in hunk.lines:
        if line.line_type != "add" or line.content.strip() == "":
            continue
        text = line.content
        lineno = line.new_lineno or 1
        if not _looks_like_frontend_change(hunk.file_path, text):
            continue

        px_match = FONT_SIZE_PX_RE.search(text)
        if px_match and float(px_match.group("value")) < 12:
            issues.append(
                Issue(
                    line=lineno,
                    severity="medium",
                    message="Font size is very small and may hurt readability.",
                    evidence=text[:200],
                    confidence_source="rule_based",
                    file_path=hunk.file_path,
                )
            )

        rel_match = FONT_SIZE_REL_RE.search(text)
        if rel_match and float(rel_match.group("value")) < 0.75:
            issues.append(
                Issue(
                    line=lineno,
                    severity="medium",
                    message="Relative font size is very small and may hurt readability.",
                    evidence=text[:200],
                    confidence_source="rule_based",
                    file_path=hunk.file_path,
                )
            )

        if OUTLINE_NONE_RE.search(text):
            issues.append(
                Issue(
                    line=lineno,
                    severity="medium",
                    message="Focus outline removed; keyboard users may lose a visible focus indicator.",
                    evidence=text[:200],
                    confidence_source="rule_based",
                    file_path=hunk.file_path,
                )
            )

        for match in CSS_DECLARATION_RE.finditer(text):
            normalized = _normalize_color(match.group("value"))
            if normalized is None:
                continue
            prop = match.group("prop").lower()
            if prop == "color":
                color_declarations.append((lineno, normalized, text[:200]))
            else:
                background_declarations.append((lineno, normalized, text[:200]))

    for color_lineno, color_value, color_text in color_declarations:
        for bg_lineno, bg_value, bg_text in background_declarations:
            if color_value != bg_value:
                continue
            issue_line = max(color_lineno, bg_lineno)
            issue_key = (issue_line, color_value)
            if issue_key in emitted_keys:
                continue
            evidence = color_text if color_lineno == bg_lineno else f"{color_text} | {bg_text}"
            issues.append(
                Issue(
                    line=issue_line,
                    severity="high",
                    message="Text color matches the background color, which can make content unreadable.",
                    evidence=evidence[:200],
                    confidence_source="rule_based",
                    file_path=hunk.file_path,
                )
            )
            emitted_keys.add(issue_key)

    return issues


def _attach_file_paths_to_llm_issues(issues: List[Issue], hunks: List[DiffHunk]) -> None:
    if not issues or not hunks:
        return

    file_paths = {h.file_path for h in hunks}
    single_file_path = next(iter(file_paths)) if len(file_paths) == 1 else None

    for issue in issues:
        if issue.file_path:
            continue
        if single_file_path is not None:
            issue.file_path = single_file_path
            continue
        for hunk in hunks:
            added_lines = [line.new_lineno for line in hunk.lines if line.line_type == "add" and line.new_lineno]
            if not added_lines:
                continue
            if min(added_lines) <= issue.line <= max(added_lines):
                issue.file_path = hunk.file_path
                break


class StyleAgent(BaseAgent):
    agent_name = "style"
    empty_confidence = 0.5

    def build_tool_plan(self, diff_text: str) -> Sequence[ToolInvocation]:
        parsed = parse_diff(diff_text)
        changed_files = extract_changed_files(parsed)[:2]
        plan: List[ToolInvocation] = [
            ToolInvocation(
                tool="search_codebase",
                args={"query": "style", "limit": 3},
                rationale="Find nearby repository conventions to compare against the diff.",
            )
        ]
        for file_path in changed_files[:2]:
            plan.append(
                ToolInvocation(
                    tool="read_file",
                    args={"path": file_path, "start_line": 1, "end_line": 120},
                    rationale=f"Inspect the changed file {file_path} for surrounding style context.",
                )
            )
        if changed_files:
            plan.append(
                ToolInvocation(
                    tool="run_linter",
                    args={"path": changed_files[0]},
                    rationale="Gather lightweight syntax and formatting signals for the primary changed file.",
                )
            )
        return plan

    def synthesize_issues(self, diff_text: str, tool_outputs: Dict[str, Any]) -> List[Issue]:
        parsed = parse_diff(diff_text)
        changed_files = extract_changed_files(parsed)[:MAX_FILES_PER_PR]
        relevant_hunks: List[DiffHunk] = []
        for file_path in changed_files:
            relevant_hunks.extend(parsed.get(file_path, []))

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
                            file_path=hunk.file_path,
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
                            file_path=hunk.file_path,
                        )
                    )
            issues.extend(_detect_frontend_design_issues(hunk))

        repo_examples: List[str] = []
        retrieved = tool_outputs.get("search_codebase") or []
        for item in retrieved:
            path = item.get("path", "unknown")
            content = item.get("content", "")
            repo_examples.append(f"# {path}\n{content}")
        if not repo_examples:
            for path, code in retrieve_similar_code("\n".join(h.header for h in relevant_hunks)):
                repo_examples.append(f"# {path}\n{code[:400]}")

        llm_issues: List[Issue] = []
        pr_id = self.repo_metadata.get("pr_id")
        if diff_text:
            from prguard_ai.reliability.circuit_breaker import CircuitBreakerError
            from prguard_ai.llm.client import TokenBudgetExceededError

            try:
                prompt = _build_llm_input(diff_text, repo_examples)
                text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
                llm_issues = _parse_llm_issues(text)
                _attach_file_paths_to_llm_issues(llm_issues, relevant_hunks)
                self.reasoning_trace.append("style: synthesized LLM findings after grounding with repo examples")
            except (CircuitBreakerError, TokenBudgetExceededError) as exc:
                logger.warning("Style agent LLM skipped (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
                self.llm_skipped = True
                self.reasoning_trace.append("style: skipped LLM synthesis due to circuit breaker or budget limits")

        return issues + llm_issues

    def score_confidence(self, issues: List[Issue]) -> float:
        return estimate_issue_confidence(issues, empty_confidence=self.empty_confidence)

    @staticmethod
    def refine(initial_output: AgentOutput, context: ReviewContext) -> tuple[str, AgentOutput]:
        """Refine style agent issues and generate a dialogue message based on context."""
        from prguard_ai.confidence.scoring_engine import estimate_issue_confidence

        refine_prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "style_refine_prompt.txt"
        if refine_prompt_path.exists():
            refine_prompt_base = refine_prompt_path.read_text(encoding="utf-8")
        else:
            refine_prompt_base = (
                "You are a code review assistant focusing on STYLE and CONSISTENCY refinement. "
                "Respond with a JSON object containing message and issues."
            )

        own_findings_str = json.dumps([issue.model_dump() for issue in initial_output.issues], indent=2)

        other_findings_list = []
        for name, output in context.agent_outputs.items():
            if name != "style":
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
            from prguard_ai.llm.client import extract_json_obj_from_llm_response
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
                    logger.warning("Style agent refinement hit maximum issue limit (20). Skipping remaining issues.")
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
                    # Default to the first changed file if ambiguous
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

            confidence = estimate_issue_confidence(final_issues, empty_confidence=0.5)
            refined_output = AgentOutput(agent="style", confidence=confidence, issues=final_issues)
        except (CircuitBreakerError, TokenBudgetExceededError) as exc:
            logger.warning("Style agent LLM skipped in refine (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
            refined_output = initial_output.model_copy(update={"llm_skipped": True})
            message = "LLM refinement skipped due to circuit breaker or budget constraints."

        return message, refined_output


def analyze_style(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """Analyze style issues in the diff using rule-based and tool-grounded reasoning."""
    return StyleAgent(repo_metadata).run_react_loop(diff_text)


__all__ = ["analyze_style", "StyleAgent"]
