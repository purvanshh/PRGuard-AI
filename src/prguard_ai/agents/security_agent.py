"""Security analysis agent for PRGuard AI."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence

from prguard_ai.agents.base_agent import BaseAgent
from prguard_ai.agents.tools.tool_args import (
    ToolArgs,
    DependencyScanArgs,
    SecretScanArgs,
    SearchCodebaseArgs,
    CveLookupArgs,
    CheckAuthPatternsArgs,
)
from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
from prguard_ai.analysis.diff_parser import DiffHunk, parse_diff
from prguard_ai.llm.client import generate_analysis, parse_agent_issues
from prguard_ai.schemas.agent_output import AgentOutput, Issue
from prguard_ai.schemas.context import ReviewContext
from prguard_ai.security.prompt_injection import response_is_suspicious, wrap_diff

from prguard_ai.config.settings import settings

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "security_prompt.txt"
MAX_FILES_PER_PR = settings.max_files_per_pr
MAX_TOKENS_PER_AGENT = 2000


SUSPECT_KEYWORDS = ["eval(", "exec(", "subprocess.Popen", "os.system"]


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


def _load_prompt() -> str:
    from prguard_ai.prompts import load_prompt

    prompt, _version = load_prompt(
        "security",
        fallback=(
            "You are a code review assistant focusing on SECURITY. "
            "Respond with a JSON array of issues."
        ),
    )
    return prompt


def _detect_sql_pattern(line: str) -> bool:
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
        return parse_agent_issues(raw)[:20]
    except Exception:
        logger.warning("Failed to parse structured LLM security response. Raw: %s", raw[:500], exc_info=True)
        return []


class SecurityAgent(BaseAgent):
    agent_name = "security"
    empty_confidence = 0.55

    def analyze_tool_needs(self, diff_text: str, changed_files: List[str]) -> Sequence[ToolArgs]:
        needs: list[ToolArgs] = [DependencyScanArgs()]
        combined = diff_text.lower()
        if any(term in combined for term in ["secret", "token", "password", "key", "auth", "credential"]):
            needs.append(SecretScanArgs(path="."))
            needs.append(SearchCodebaseArgs(query="secret"))
        needs.append(CveLookupArgs())
        has_python = any(f.endswith(".py") for f in changed_files)
        if has_python and any(term in combined for term in ["auth", "login", "permission", "role", "admin"]):
            needs.append(CheckAuthPatternsArgs(file_path="."))
        return needs[:3]

    def detect_suspicious_findings(self, issues: List[Issue], diff_text: str) -> List[str]:
        for issue in issues:
            msg = issue.message.lower()
            if any(t in msg for t in ["dependency", "package", "library", "version"]):
                return ["dependency_scan"]
            if any(t in msg for t in ["file", "path", "read", "write", "open"]):
                return ["read_file"]
            if any(t in msg for t in ["cve", "vulnerability", "vulnerable"]):
                return ["cve_lookup"]
            if any(t in msg for t in ["secret", "token", "credential", "api key"]):
                return ["secret_scan"]
            if any(t in msg for t in ["auth", "login", "permission", "authorization"]):
                return ["check_auth_patterns"]
        return []

    def synthesize_issues(self, diff_text: str, tool_outputs: Dict[str, Any]) -> List[Issue]:
        pr_id = self.repo_metadata.get("pr_id")
        parsed = parse_diff(diff_text)

        files = list(parsed.keys())[:MAX_FILES_PER_PR]
        file_hunks: List[DiffHunk] = []
        for filename in files:
            file_hunks.extend(parsed[filename])

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
            issues.extend(DetectorRegistry.match_all("security", diff_lines, h.file_path, full_text, frozenset(added_set)))

        dep_scan = tool_outputs.get("dependency_scan") or {}
        for suspicious in dep_scan.get("suspicious", []):
            issues.append(
                Issue(
                    line=1,
                    severity="medium",
                    message=f"Dependency manifest contains risky token `{suspicious.get('token')}`.",
                    evidence=suspicious.get("path", ""),
                    confidence_source="inferred",
                    file_path=suspicious.get("path"),
                )
            )

        llm_issues: List[Issue] = []
        if diff_text:
            from prguard_ai.reliability.circuit_breaker import CircuitBreakerError
            from prguard_ai.llm.client import TokenBudgetExceededError

            try:
                extra_context = json.dumps(tool_outputs, indent=2)[:2000]
                prompt = _load_prompt() + "\n\n--- Diff ---\n" + wrap_diff(diff_text) + "\n\n--- Tool context ---\n" + extra_context
                text, _usage = generate_analysis(prompt, max_tokens=MAX_TOKENS_PER_AGENT, pr_id=pr_id)
                if response_is_suspicious(text, diff_text):
                    logger.warning("Security agent: suspicious LLM response for PR %s — possible prompt injection", pr_id)
                    self.reasoning_trace.append("security: flagged potential prompt injection for manual review")
                llm_issues = _parse_llm_issues(text)
                self.reasoning_trace.append("security: synthesized LLM findings after dependency and history checks")
            except (CircuitBreakerError, TokenBudgetExceededError) as exc:
                logger.warning("Security agent LLM skipped (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
                self.llm_skipped = True
                self.reasoning_trace.append("security: skipped LLM synthesis due to circuit breaker or budget limits")

        return issues + llm_issues

    def score_confidence(self, issues: List[Issue]) -> float:
        return estimate_issue_confidence(issues, empty_confidence=self.empty_confidence)

    @staticmethod
    def refine(initial_output: AgentOutput, context: ReviewContext) -> tuple[str, AgentOutput]:
        """Refine security agent issues and generate a dialogue message based on context."""
        from prguard_ai.confidence.scoring_engine import estimate_issue_confidence
        from prguard_ai.analysis.diff_parser import extract_changed_files

        refine_prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "security_refine_prompt.txt"
        if refine_prompt_path.exists():
            refine_prompt_base = refine_prompt_path.read_text(encoding="utf-8")
        else:
            refine_prompt_base = (
                "You are a code review assistant focusing on SECURITY refinement. "
                "Respond with a JSON object containing message and issues."
            )

        own_findings_str = json.dumps([issue.model_dump() for issue in initial_output.issues], indent=2)

        other_findings_list = []
        for name, output in context.agent_outputs.items():
            if name != "security":
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
                    logger.warning("Security agent refinement hit maximum issue limit (20). Skipping remaining issues.")
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

            confidence = estimate_issue_confidence(final_issues, empty_confidence=0.55)
            refined_output = AgentOutput(agent="security", confidence=confidence, issues=final_issues)
        except (CircuitBreakerError, TokenBudgetExceededError) as exc:
            logger.warning("Security agent LLM skipped in refine (circuit breaker open or budget exceeded) for PR %s: %s", pr_id, exc)
            refined_output = initial_output.model_copy(update={"llm_skipped": True})
            message = "LLM refinement skipped due to circuit breaker or budget constraints."

        return message, refined_output


def analyze_security(diff_text: str, repo_metadata: Dict[str, Any] | None = None) -> AgentOutput:
    """Detect security issues with local tool support and LLM synthesis."""
    return SecurityAgent(repo_metadata).run_react_loop(diff_text)


__all__ = [
    "analyze_security",
    "detect_eval_usage",
    "detect_hardcoded_secrets",
    "SecurityAgent",
]
