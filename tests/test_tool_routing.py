"""Tests for typed tool routing (Phase 8)."""

import pytest

from prguard_ai.agents.base_agent import BaseAgent
from prguard_ai.agents.tools.tool_args import (
    ReadFileArgs,
    RunLinterArgs,
    RunTestArgs,
    CheckFormattingArgs,
    GetRepoStyleGuideArgs,
    SecretScanArgs,
    DependencyScanArgs,
    CheckAuthPatternsArgs,
    GetTypeInfoArgs,
    SymbolicExecuteArgs,
    SearchCodebaseArgs,
    CheckDeadCodeArgs,
    CveLookupArgs,
)


@pytest.fixture
def mock_llm():
    from unittest.mock import MagicMock
    from prguard_ai.llm.client import LLMClient
    client = MagicMock(spec=LLMClient)
    return client


class StyleAgent(BaseAgent):
    agent_name = "style"

    def synthesize_issues(self, diff_text, tool_outputs):
        return []

    def detect_suspicious_findings(self, issues, diff_text):
        return []

    def score_confidence(self, issues):
        return 0.5

    def analyze_tool_needs(self, diff_text, changed_files):
        tools = []
        python_files = [f for f in changed_files if f.endswith('.py')]
        if python_files:
            tools.append(RunLinterArgs(linter="ruff", path=python_files[0]))
            tools.append(CheckFormattingArgs(path=python_files[0]))
        js_files = [f for f in changed_files if f.endswith(('.js', '.ts', '.tsx'))]
        if js_files:
            tools.append(CheckFormattingArgs(path=js_files[0]))
        tools.append(GetRepoStyleGuideArgs())
        return tools


class SecurityAgent(BaseAgent):
    agent_name = "security"

    def synthesize_issues(self, diff_text, tool_outputs):
        return []

    def detect_suspicious_findings(self, issues, diff_text):
        return []

    def score_confidence(self, issues):
        return 0.5

    def analyze_tool_needs(self, diff_text, changed_files):
        tools = []
        for f in changed_files:
            tools.append(SecretScanArgs(path=f))
        if any(f.endswith(('requirements.txt', 'package.json')) for f in changed_files):
            manifest = next(f for f in changed_files if f.endswith(('requirements.txt', 'package.json')))
            tools.append(DependencyScanArgs(manifest_path=manifest))
        auth_keywords = ['auth', 'login', 'password', 'token', 'session', 'jwt']
        if any(kw in diff_text.lower() for kw in auth_keywords):
            for f in changed_files:
                tools.append(CheckAuthPatternsArgs(file_path=f))
        return tools


def test_style_agent_returns_typed_args(mock_llm):
    agent = StyleAgent(llm=mock_llm)
    tools = agent.analyze_tool_needs("diff", ["app.py", "style.css"])

    assert any(isinstance(t, RunLinterArgs) for t in tools)
    assert any(isinstance(t, CheckFormattingArgs) for t in tools)
    assert any(isinstance(t, GetRepoStyleGuideArgs) for t in tools)


def test_security_agent_scans_secrets(mock_llm):
    agent = SecurityAgent(llm=mock_llm)
    tools = agent.analyze_tool_needs("auth login", ["auth.py", "requirements.txt"])

    assert any(isinstance(t, SecretScanArgs) for t in tools)
    assert any(isinstance(t, DependencyScanArgs) for t in tools)
    assert any(isinstance(t, CheckAuthPatternsArgs) for t in tools)


def test_new_agent_no_base_class_changes(mock_llm):
    class CustomAgent(BaseAgent):
        agent_name = "custom"

        def synthesize_issues(self, diff_text, tool_outputs):
            return []

        def detect_suspicious_findings(self, issues, diff_text):
            return []

        def score_confidence(self, issues):
            return 0.5

        def analyze_tool_needs(self, diff_text, changed_files):
            return [ReadFileArgs(path="test.py")]

    agent = CustomAgent(llm=mock_llm)
    tools = agent.analyze_tool_needs("", ["test.py"])
    assert len(tools) == 1
    assert isinstance(tools[0], ReadFileArgs)
