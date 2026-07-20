"""Reusable tool-driven agent foundation for PRGuard AI with true ReAct loop."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

logger = logging.getLogger(__name__)

from prguard_ai.agents.tools import AgentToolExecutor, ToolCallRecord, ToolInvocation
from prguard_ai.llm.client import LLMClient, LLMIssueResponse, LLMRefineResponse
from prguard_ai.policy.engine import apply_policy_to_issues, filter_diff_by_policy, load_effective_policy
from prguard_ai.schemas.agent_output import AgentOutput, Issue


class BaseAgent(ABC):
    """Base class implementing a true ReAct loop with dynamic tool selection."""

    agent_name: str = "base"
    empty_confidence: float = 0.5
    max_react_iterations: int = 3

    def __init__(
        self,
        repo_metadata: Dict[str, Any] | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.repo_metadata = repo_metadata or {}
        self.executor = AgentToolExecutor(self.repo_metadata)
        self.llm = llm or LLMClient()
        self.reasoning_trace: List[str] = []
        self.tool_records: List[ToolCallRecord] = []
        self.llm_skipped: bool = False
        self.policy = load_effective_policy(self.repo_metadata)

    @abstractmethod
    def analyze_tool_needs(self, diff_text: str, changed_files: List[str]) -> List[str]:
        """Examine the diff and decide which tools are relevant. Return tool names."""

    @abstractmethod
    def synthesize_issues(self, diff_text: str, tool_outputs: Dict[str, Any]) -> List[Issue]:
        """Produce issues after seeing tool outputs."""

    @abstractmethod
    def detect_suspicious_findings(self, issues: List[Issue], diff_text: str) -> List[str]:
        """Return tool names to call for verification based on LLM findings."""

    @abstractmethod
    def score_confidence(self, issues: List[Issue]) -> float:
        """Return the aggregate confidence score for the current issue set."""

    def _build_tool_plan(self, diff_text: str, changed_files: List[str]) -> Sequence[ToolInvocation]:
        tool_names = self.analyze_tool_needs(diff_text, changed_files)
        plan: List[ToolInvocation] = []
        for name in tool_names:
            args = self._args_for_tool(name, changed_files)
            plan.append(ToolInvocation(tool=name, args=args, rationale=f"Dynamic need: {name}"))
        return plan

    def _args_for_tool(self, tool: str, changed_files: List[str]) -> Dict[str, Any]:
        if tool == "read_file" and changed_files:
            return {"path": changed_files[0], "start_line": 1, "end_line": 120}
        if tool == "run_linter" and changed_files:
            return {"path": changed_files[0]}
        if tool == "search_codebase":
            term = "secret" if self.agent_name == "security" else ("error" if self.agent_name == "logic" else "style")
            return {"query": term, "limit": 3}
        if tool == "git_blame" and changed_files:
            return {"path": changed_files[0], "line": 1}
        if tool == "get_type_info" and changed_files:
            return {"path": changed_files[0]}
        if tool == "dependency_scan":
            return {}
        if tool == "run_test":
            return {"target": "tests"}
        if tool == "check_formatting" and changed_files:
            return {"path": changed_files[0]}
        if tool == "get_repo_style_guide":
            return {}
        if tool == "symbolic_execute" and changed_files:
            return {"path": changed_files[0], "function": ""}
        if tool == "check_dead_code" and changed_files:
            return {"path": changed_files[0]}
        if tool == "cve_lookup":
            return {}
        if tool == "secret_scan":
            return {"path": "."}
        if tool == "check_auth_patterns":
            return {"path": "."}
        return {}

    def _execute_tools(self, plan: Sequence[ToolInvocation]) -> Dict[str, Any]:
        tool_outputs: Dict[str, Any] = {}
        for invocation in plan:
            self.reasoning_trace.append(
                f"{self.agent_name}: plan tool={invocation.tool} because {invocation.rationale or 'evidence gathering'}"
            )
            result = self.executor.execute(invocation)
            tool_outputs[invocation.tool] = result.output
            self.reasoning_trace.append(
                f"{self.agent_name}: reflect tool={invocation.tool} status={'ok' if result.ok else 'error'}"
            )
            self.tool_records.append(ToolCallRecord(invocation=invocation, result=result))
        return tool_outputs

    def _verify_with_tools(self, issues: List[Issue], diff_text: str, tool_outputs: Dict[str, Any]) -> Dict[str, Any]:
        suspicious = self.detect_suspicious_findings(issues, diff_text)
        for tool_name in suspicious:
            if tool_name in tool_outputs:
                continue
            changed = [k for k in ["read_file", "run_linter", "git_blame", "check_formatting", "check_dead_code", "secret_scan"] if k in self.executor.available_tools]
            args = self._args_for_tool(tool_name, changed)
            self.reasoning_trace.append(f"{self.agent_name}: verifying suspicious finding with tool={tool_name}")
            result = self.executor.execute(ToolInvocation(tool=tool_name, args=args, rationale="verification"))
            tool_outputs[tool_name] = result.output
            self.tool_records.append(ToolCallRecord(
                invocation=ToolInvocation(tool=tool_name, args=args, rationale="verification"),
                result=result,
            ))
        return tool_outputs

    def run_react_loop(self, diff_text: str) -> AgentOutput:
        from prguard_ai.security.prompt_injection import PromptInjectionDetector, sanitize_diff_for_prompt

        detector = PromptInjectionDetector()
        check = detector.detect(diff_text)
        if check.risk_score > 0.7:
            logger.critical(
                "High-risk injection detected: %s", check.matched_patterns
            )
            return AgentOutput(
                agent=self.agent_name,
                issues=[
                    Issue(
                        line=0,
                        severity="high",
                        message="Potential prompt injection detected in PR diff. Manual review required.",
                        evidence="",
                        confidence_source="rule_based",
                        verified=True,
                    )
                ],
                llm_skipped=True,
            )
        if check.risk_score > 0.3:
            logger.warning(
                "Medium-risk content flagged: %s", check.matched_patterns
            )
        diff_text = sanitize_diff_for_prompt(diff_text)
        diff_text = filter_diff_by_policy(diff_text, self.policy)
        self.reasoning_trace.append(f"{self.agent_name}: observe diff and determine tool needs")

        from prguard_ai.analysis.diff_parser import extract_changed_files, parse_diff
        parsed = parse_diff(diff_text)
        changed_files = extract_changed_files(parsed)

        plan = self._build_tool_plan(diff_text, list(changed_files)[:5])
        tool_outputs = self._execute_tools(plan)

        issues = self.synthesize_issues(diff_text, tool_outputs)

        for iteration in range(self.max_react_iterations - 1):
            tool_outputs = self._verify_with_tools(issues, diff_text, tool_outputs)
            new_issues = self.synthesize_issues(diff_text, tool_outputs)
            if len(new_issues) == len(issues):
                break
            issues = new_issues

        issues = apply_policy_to_issues(issues, self.policy)
        return AgentOutput(
            agent=self.agent_name,
            confidence=self.score_confidence(issues),
            issues=issues,
            llm_skipped=self.llm_skipped,
            reasoning_trace=self.reasoning_trace,
            tool_calls=[record.model_dump() for record in self.tool_records],
        )

    def _synthesize_with_llm(
        self,
        prompt: str,
        pr_id: str | None = None,
    ) -> list[Issue]:
        try:
            response = self.llm.generate_analysis(
                prompt=prompt,
                response_schema=LLMIssueResponse,
            )
            return response.issues
        except Exception:
            from prguard_ai.llm.client import generate_analysis, parse_agent_issues
            text, _ = generate_analysis(prompt, max_tokens=512, pr_id=pr_id)
            return parse_agent_issues(text)

    def _refine_with_llm(
        self,
        prompt: str,
        pr_id: str | None = None,
    ) -> tuple[list[Issue], list[Issue], list[int]]:
        try:
            response = self.llm.generate_analysis(
                prompt=prompt,
                response_schema=LLMRefineResponse,
            )
            return response.refined_issues, response.new_findings, response.dropped_findings
        except Exception:
            from prguard_ai.llm.client import generate_analysis
            from prguard_ai.llm.client import parse_agent_output
            text, _ = generate_analysis(prompt, max_tokens=512, pr_id=pr_id)
            try:
                parsed = parse_agent_output(text)
                return parsed.issues, [], []
            except Exception:
                return [], [], []

    def _prompt_json(self, prompt: str, *, max_tokens: int, pr_id: str | None = None, expect_object: bool = False) -> Any:
        from prguard_ai.llm.client import (
            generate_analysis,
        )

        raw, _usage = generate_analysis(prompt, max_tokens=max_tokens, pr_id=pr_id)
        from prguard_ai.llm.client import parse_agent_issues, parse_agent_output
        if expect_object:
            return parse_agent_output(raw)
        return parse_agent_issues(raw)

    def refine_with_tools(self, ctx: Any, agent_output: AgentOutput) -> tuple[str, AgentOutput]:
        from prguard_ai.analysis.diff_parser import extract_changed_files
        from prguard_ai.schemas.context import DialogueTurn

        changed = extract_changed_files(ctx.diff_text)

        for turn in list(ctx.dialogue):
            if turn.speaker != "coordinator":
                continue
            msg = turn.message.lower()
            if ("file" in msg or "path" in msg) and changed:
                result = self.executor.execute(
                    ToolInvocation(tool="read_file",
                                   args={"path": changed[0], "start_line": 1, "end_line": 60},
                                   rationale="verify coordinator file reference")
                )
                output = result.output or {}
                ctx.dialogue.append(DialogueTurn(
                    speaker=self.agent_name,
                    message=f"[tool:read_file] {changed[0]}: {str(output.get('content', ''))[:300]}"
                ))
                self.tool_records.append(ToolCallRecord(
                    invocation=ToolInvocation(tool="read_file",
                                              args={"path": changed[0], "start_line": 1, "end_line": 60},
                                              rationale="refinement read"),
                    result=result,
                ))
            if "test" in msg or "error" in msg:
                result = self.executor.execute(
                    ToolInvocation(tool="run_test", args={"target": "tests"},
                                   rationale="verify coordinator test/error reference")
                )
                out = result.output or {}
                ctx.dialogue.append(DialogueTurn(
                    speaker=self.agent_name,
                    message=f"[tool:run_test] exit={out.get('returncode')}: {out.get('stdout', '')[:200]}"
                ))
                self.tool_records.append(ToolCallRecord(
                    invocation=ToolInvocation(tool="run_test", args={"target": "tests"},
                                              rationale="refinement test"),
                    result=result,
                ))
            if "secret" in msg or "token" in msg or "vulnerab" in msg:
                result = self.executor.execute(
                    ToolInvocation(tool="dependency_scan", args={},
                                   rationale="verify coordinator security reference")
                )
                ctx.dialogue.append(DialogueTurn(
                    speaker=self.agent_name,
                    message=f"[tool:dependency_scan] {str(result.output)[:300]}"
                ))
                self.tool_records.append(ToolCallRecord(
                    invocation=ToolInvocation(tool="dependency_scan", args={},
                                              rationale="refinement dep scan"),
                    result=result,
                ))

        return self.refine(agent_output, ctx)
