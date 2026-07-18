"""Reusable tool-driven agent foundation for PRGuard AI."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

from prguard_ai.agents.tools import AgentToolExecutor, ToolCallRecord, ToolInvocation
from prguard_ai.schemas.agent_output import AgentOutput, Issue


class BaseAgent(ABC):
    """Base class implementing a lightweight observe-plan-act-reflect loop."""

    agent_name: str = "base"
    empty_confidence: float = 0.5

    def __init__(self, repo_metadata: Dict[str, Any] | None = None) -> None:
        self.repo_metadata = repo_metadata or {}
        self.executor = AgentToolExecutor(self.repo_metadata)
        self.reasoning_trace: List[str] = []
        self.tool_records: List[ToolCallRecord] = []
        self.llm_skipped: bool = False

    @abstractmethod
    def build_tool_plan(self, diff_text: str) -> Sequence[ToolInvocation]:
        """Return the tool calls the agent wants to make before final synthesis."""

    @abstractmethod
    def synthesize_issues(self, diff_text: str, tool_outputs: Dict[str, Any]) -> List[Issue]:
        """Produce issues after seeing tool outputs."""

    @abstractmethod
    def score_confidence(self, issues: List[Issue]) -> float:
        """Return the aggregate confidence score for the current issue set."""

    def run_react_loop(self, diff_text: str) -> AgentOutput:
        self.reasoning_trace.append(f"{self.agent_name}: observe diff and collect grounded evidence")
        tool_outputs: Dict[str, Any] = {}

        for invocation in self.build_tool_plan(diff_text):
            self.reasoning_trace.append(f"{self.agent_name}: plan tool={invocation.tool} because {invocation.rationale or 'evidence gathering'}")
            result = self.executor.execute(invocation)
            tool_outputs[invocation.tool] = result.output
            self.reasoning_trace.append(
                f"{self.agent_name}: reflect tool={invocation.tool} status={'ok' if result.ok else 'error'}"
            )
            self.tool_records.append(ToolCallRecord(invocation=invocation, result=result))

        issues = self.synthesize_issues(diff_text, tool_outputs)
        return AgentOutput(
            agent=self.agent_name,
            confidence=self.score_confidence(issues),
            issues=issues,
            llm_skipped=self.llm_skipped,
            reasoning_trace=self.reasoning_trace,
            tool_calls=[record.model_dump() for record in self.tool_records],
        )

    def _prompt_json(self, prompt: str, *, max_tokens: int, pr_id: str | None = None, expect_object: bool = False) -> Any:
        from prguard_ai.llm.client import (
            extract_json_from_llm_response,
            extract_json_obj_from_llm_response,
            generate_analysis,
        )

        raw, _usage = generate_analysis(prompt, max_tokens=max_tokens, pr_id=pr_id)
        extracted = extract_json_obj_from_llm_response(raw) if expect_object else extract_json_from_llm_response(raw)
        return json.loads(extracted)
