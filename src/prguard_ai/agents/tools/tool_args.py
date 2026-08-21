"""Typed tool argument schemas. No string switches, no raw dicts."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class ToolArgs(BaseModel):
    tool_name: str
    args: dict = {}


class ReadFileArgs(ToolArgs):
    tool_name: Literal["read_file"] = "read_file"
    path: str
    line: int | None = None
    context_lines: int = 3


class RunLinterArgs(ToolArgs):
    tool_name: Literal["run_linter"] = "run_linter"
    linter: Literal["ruff", "black", "flake8"] = "ruff"
    path: str = "."


class RunTestArgs(ToolArgs):
    tool_name: Literal["run_test"] = "run_test"
    test_path: str = "tests"
    function_name: str | None = None


class SearchCodebaseArgs(ToolArgs):
    tool_name: Literal["search_codebase"] = "search_codebase"
    query: str
    file_pattern: str = "*"


class DependencyScanArgs(ToolArgs):
    tool_name: Literal["dependency_scan"] = "dependency_scan"
    manifest_path: str = "requirements.txt"


class GetTypeInfoArgs(ToolArgs):
    tool_name: Literal["get_type_info"] = "get_type_info"
    file_path: str
    symbol_name: str = ""


class CheckFormattingArgs(ToolArgs):
    tool_name: Literal["check_formatting"] = "check_formatting"
    path: str = "."


class GetRepoStyleGuideArgs(ToolArgs):
    tool_name: Literal["get_repo_style_guide"] = "get_repo_style_guide"


class SymbolicExecuteArgs(ToolArgs):
    tool_name: Literal["symbolic_execute"] = "symbolic_execute"
    file_path: str
    function_name: str = ""


class CheckDeadCodeArgs(ToolArgs):
    tool_name: Literal["check_dead_code"] = "check_dead_code"
    file_path: str


class CveLookupArgs(ToolArgs):
    tool_name: Literal["cve_lookup"] = "cve_lookup"
    package_name: str = ""
    version: str = ""


class SecretScanArgs(ToolArgs):
    tool_name: Literal["secret_scan"] = "secret_scan"
    path: str = "."


class CheckAuthPatternsArgs(ToolArgs):
    tool_name: Literal["check_auth_patterns"] = "check_auth_patterns"
    file_path: str = "."


class SemgrepScanArgs(ToolArgs):
    tool_name: Literal["semgrep_scan"] = "semgrep_scan"
    path: str = "."
    limit: int = 50
