"""Lightweight local tool executor for PRGuard AI agents."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from prguard_ai.agents.tools.schemas import ToolInvocation, ToolResult


def _safe_repo_root(repo_metadata: Dict[str, Any] | None = None) -> Path | None:
    meta = repo_metadata or {}
    sandbox_path = meta.get("sandbox_path")
    if sandbox_path:
        return Path(str(sandbox_path))
    return None


class AgentToolExecutor:
    """Executes a fixed set of local analysis tools for an agent."""

    def __init__(self, repo_metadata: Dict[str, Any] | None = None) -> None:
        self.repo_metadata = repo_metadata or {}
        self.repo_root = _safe_repo_root(self.repo_metadata)
        self._tools: Dict[str, Callable[[Dict[str, Any]], ToolResult]] = {
            "read_file": self._read_file,
            "search_codebase": self._search_codebase,
            "run_linter": self._run_linter,
            "run_test": self._run_test,
            "get_type_info": self._get_type_info,
            "git_blame": self._git_blame,
            "dependency_scan": self._dependency_scan,
        }

    @property
    def available_tools(self) -> List[str]:
        return sorted(self._tools)

    def execute(self, invocation: ToolInvocation) -> ToolResult:
        handler = self._tools.get(invocation.tool)
        if handler is None:
            return ToolResult(tool=invocation.tool, ok=False, error=f"Unknown tool: {invocation.tool}")
        try:
            return handler(invocation.args)
        except Exception as exc:  # pragma: no cover - defensive safety
            return ToolResult(tool=invocation.tool, ok=False, error=str(exc))

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        if self.repo_root is None:
            return path
        return self.repo_root / path

    def _read_file(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve_path(str(args.get("path", "")))
        start_line = max(int(args.get("start_line", 1)), 1)
        end_line = max(int(args.get("end_line", start_line + 40)), start_line)
        if not path.exists():
            return ToolResult(tool="read_file", ok=False, error=f"File not found: {path}")
        lines = path.read_text(encoding="utf-8").splitlines()
        snippet = lines[start_line - 1:end_line]
        return ToolResult(
            tool="read_file",
            output={"path": str(path), "start_line": start_line, "end_line": end_line, "content": "\n".join(snippet)},
        )

    def _search_codebase(self, args: Dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        limit = max(1, int(args.get("limit", 5)))
        if not query or self.repo_root is None or not self.repo_root.exists():
            return ToolResult(tool="search_codebase", output=[])
        matches: List[Dict[str, Any]] = []
        for path in self.repo_root.rglob("*"):
            if len(matches) >= limit:
                break
            if not path.is_file():
                continue
            try:
                for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if query.lower() in line.lower():
                        matches.append({"path": str(path.relative_to(self.repo_root)), "line": idx, "content": line[:200]})
                        if len(matches) >= limit:
                            break
            except Exception:
                continue
        return ToolResult(tool="search_codebase", output=matches)

    def _run_command(self, command: List[str]) -> Dict[str, Any]:
        completed = subprocess.run(
            command,
            cwd=str(self.repo_root) if self.repo_root else None,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[:2000],
            "stderr": completed.stderr[:2000],
        }

    def _run_linter(self, args: Dict[str, Any]) -> ToolResult:
        target = str(args.get("path", "."))
        command = ["python3", "-m", "compileall", target]
        return ToolResult(tool="run_linter", output=self._run_command(command))

    def _run_test(self, args: Dict[str, Any]) -> ToolResult:
        target = str(args.get("target", "tests"))
        if self.repo_root is None:
            return ToolResult(tool="run_test", output={"skipped": True, "reason": "sandbox unavailable"})
        test_path = self.repo_root / target
        if not test_path.exists():
            return ToolResult(tool="run_test", output={"skipped": True, "reason": f"missing target: {target}"})
        command = ["python3", "-m", "pytest", str(test_path), "-q", "-o", "addopts="]
        return ToolResult(tool="run_test", output=self._run_command(command))

    def _get_type_info(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve_path(str(args.get("path", "")))
        if not path.exists():
            return ToolResult(tool="get_type_info", ok=False, error=f"File not found: {path}")
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ToolResult(tool="get_type_info", ok=False, error=str(exc))
        functions: List[Dict[str, Any]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "args": [arg.arg for arg in node.args.args],
                        "returns": ast.unparse(node.returns) if node.returns is not None else None,
                    }
                )
        return ToolResult(tool="get_type_info", output={"path": str(path), "functions": functions})

    def _git_blame(self, args: Dict[str, Any]) -> ToolResult:
        path = str(args.get("path", ""))
        line = max(1, int(args.get("line", 1)))
        if self.repo_root is None:
            return ToolResult(tool="git_blame", output={"skipped": True, "reason": "sandbox unavailable"})
        command = ["git", "blame", "-L", f"{line},{line}", "--", path]
        return ToolResult(tool="git_blame", output=self._run_command(command))

    def _dependency_scan(self, args: Dict[str, Any]) -> ToolResult:
        if self.repo_root is None or not self.repo_root.exists():
            return ToolResult(tool="dependency_scan", output={"requirements": [], "suspicious": []})
        requirements = []
        suspicious = []
        for filename in ("requirements.txt", "pyproject.toml", "package.json"):
            path = self.repo_root / filename
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            requirements.append({"path": filename, "content": content[:2000]})
            lowered = content.lower()
            for token in ("*", "latest", "http://", "git+http"):
                if token in lowered:
                    suspicious.append({"path": filename, "token": token})
        return ToolResult(tool="dependency_scan", output={"requirements": requirements, "suspicious": suspicious})
