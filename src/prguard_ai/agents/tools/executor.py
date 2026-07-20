"""Lightweight local tool executor for PRGuard AI agents."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Set

from prguard_ai.agents.tools.schemas import ToolInvocation, ToolResult


def _safe_repo_root(repo_metadata: Dict[str, Any] | None = None) -> Path | None:
    meta = repo_metadata or {}
    sandbox_path = meta.get("sandbox_path")
    if sandbox_path:
        return Path(str(sandbox_path)).resolve()
    return None


SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r"""(?i)(?:api[_-]?key|secret|token|password|credential|auth[_-]?token)\s*[=:]\s*['"]([\w\-]{20,})['"]"""),
    re.compile(r"(?i)(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
    re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"(?i)(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"(?i)sk_live_[a-zA-Z0-9]{24,}"),
    re.compile(r"(?i)pk_live_[a-zA-Z0-9]{24,}"),
]
MAX_TOOL_FILE_BYTES = 1_000_000
MAX_TOOL_SCAN_FILES = 500
SKIPPED_SCAN_DIRS = {".git", ".hg", ".svn", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "dist", "build"}


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
            "check_formatting": self._check_formatting,
            "get_repo_style_guide": self._get_repo_style_guide,
            "symbolic_execute": self._symbolic_execute,
            "check_dead_code": self._check_dead_code,
            "cve_lookup": self._cve_lookup,
            "secret_scan": self._secret_scan,
            "check_auth_patterns": self._check_auth_patterns,
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
        if self.repo_root is None:
            return path.resolve()
        resolved = (path if path.is_absolute() else self.repo_root / path).resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes repository sandbox: {raw_path}") from exc
        return resolved

    def _repo_relative_path(self, raw_path: str) -> str:
        path = self._resolve_path(raw_path)
        if self.repo_root is None:
            return str(path)
        return str(path.relative_to(self.repo_root))

    def _is_inside_repo(self, path: Path) -> bool:
        if self.repo_root is None:
            return True
        try:
            path.resolve().relative_to(self.repo_root)
        except ValueError:
            return False
        return True

    def _is_scannable_file(self, path: Path) -> bool:
        if not path.is_file() or not self._is_inside_repo(path):
            return False
        if any(part in SKIPPED_SCAN_DIRS for part in path.parts):
            return False
        try:
            return path.stat().st_size <= MAX_TOOL_FILE_BYTES
        except OSError:
            return False

    def _read_file(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve_path(str(args.get("path", "")))
        start_line = max(int(args.get("start_line", 1)), 1)
        end_line = max(int(args.get("end_line", start_line + 40)), start_line)
        if not path.exists():
            return ToolResult(tool="read_file", ok=False, error=f"File not found: {path}")
        if path.stat().st_size > MAX_TOOL_FILE_BYTES:
            return ToolResult(tool="read_file", ok=False, error=f"File too large for tool read: {path}")
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
        scanned = 0
        for path in self.repo_root.rglob("*"):
            if len(matches) >= limit:
                break
            if not self._is_scannable_file(path):
                continue
            scanned += 1
            if scanned > MAX_TOOL_SCAN_FILES:
                break
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
        target = self._repo_relative_path(str(args.get("path", ".")))
        command = ["python3", "-m", "compileall", target]
        return ToolResult(tool="run_linter", output=self._run_command(command))

    def _run_test(self, args: Dict[str, Any]) -> ToolResult:
        target = str(args.get("target", "tests"))
        if self.repo_root is None:
            return ToolResult(tool="run_test", output={"skipped": True, "reason": "sandbox unavailable"})
        test_path = self._resolve_path(target)
        if not test_path.exists():
            return ToolResult(tool="run_test", output={"skipped": True, "reason": f"missing target: {target}"})
        command = ["python3", "-m", "pytest", str(test_path.relative_to(self.repo_root)), "-q", "-o", "addopts="]
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
        command = ["git", "blame", "-L", f"{line},{line}", "--", self._repo_relative_path(path)]
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

    def _check_formatting(self, args: Dict[str, Any]) -> ToolResult:
        target_path = self._resolve_path(str(args.get("path", ".")))
        target = str(target_path)
        if not Path(target).exists():
            return ToolResult(tool="check_formatting", output={"skipped": True, "reason": f"missing target: {target}"})
        command = ["python3", "-m", "ruff", "format", "--check", "--diff", target]
        result = self._run_command(command)
        if result["returncode"] == 0:
            return ToolResult(tool="check_formatting", output={"status": "formatted", "detail": "No formatting issues found."})
        lines = [l for l in result["stdout"].splitlines() if l.startswith(("+", "-"))][:30]
        return ToolResult(
            tool="check_formatting",
            output={"status": "needs_formatting", "detail": f"Ruff format diff ({len(lines)} lines)", "diff_lines": lines},
        )

    def _get_repo_style_guide(self, args: Dict[str, Any]) -> ToolResult:
        if self.repo_root is None or not self.repo_root.exists():
            return ToolResult(tool="get_repo_style_guide", output={"skipped": True, "reason": "sandbox unavailable"})
        configs: Dict[str, Any] = {}
        for fname in (".editorconfig", "ruff.toml", ".ruff.toml", "pyproject.toml", ".pre-commit-config.yaml", ".style.yapf"):
            path = self.repo_root / fname
            if path.exists():
                configs[fname] = path.read_text(encoding="utf-8")[:2000]
        return ToolResult(tool="get_repo_style_guide", output=configs)

    def _symbolic_execute(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve_path(str(args.get("path", "")))
        func_name = str(args.get("function", ""))
        if not path.exists():
            return ToolResult(tool="symbolic_execute", ok=False, error=f"File not found: {path}")
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ToolResult(tool="symbolic_execute", ok=False, error=str(exc))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and (not func_name or node.name == func_name):
                paths: List[List[str]] = []
                self._trace_paths(node.body, [], paths)
                return ToolResult(
                    tool="symbolic_execute",
                    output={"function": node.name, "paths": paths, "path_count": len(paths), "line": node.lineno},
                )
        return ToolResult(tool="symbolic_execute", output={"function": func_name or "any", "paths": [], "path_count": 0})

    def _trace_paths(self, stmts: List[ast.stmt], current: List[str], result: List[List[str]]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                tag = type(stmt).__name__
                current.append(tag)
                result.append(list(current))
                return
            if isinstance(stmt, ast.If):
                cond = ast.unparse(stmt.test)[:60]
                current.append(f"if {cond}")
                self._trace_paths(stmt.body, list(current), result)
                if stmt.orelse:
                    current.append("else")
                    self._trace_paths(stmt.orelse, list(current), result)
                return
            tag = type(stmt).__name__
            current.append(f"{tag}")
        result.append(list(current))

    def _check_dead_code(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve_path(str(args.get("path", "")))
        if not path.exists():
            return ToolResult(tool="check_dead_code", ok=False, error=f"File not found: {path}")
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ToolResult(tool="check_dead_code", ok=False, error=str(exc))
        dead: List[Dict[str, Any]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            self._find_dead_after_jump(node.body, dead, path)
        return ToolResult(tool="check_dead_code", output={"dead_code_regions": dead})

    def _find_dead_after_jump(self, stmts: List[ast.stmt], dead: List[Dict[str, Any]], file_path: Path) -> None:
        for i, stmt in enumerate(stmts[:-1]):
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                next_stmt = stmts[i + 1]
                if isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Constant):
                    continue
                dead.append({
                    "after_line": stmt.lineno,
                    "dead_line": next_stmt.lineno,
                    "dead_type": type(next_stmt).__name__,
                    "dead_text": ast.unparse(next_stmt)[:120],
                })

    def _cve_lookup(self, args: Dict[str, Any]) -> ToolResult:
        if self.repo_root is None or not self.repo_root.exists():
            return ToolResult(tool="cve_lookup", output={"scanned": False})
        findings: List[Dict[str, Any]] = []
        for filename in ("requirements.txt", "pyproject.toml"):
            path = self.repo_root / filename
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "-", "[")):
                    continue
                if "==" in stripped:
                    pkg, ver = stripped.split("==", 1)
                    findings.append({"package": pkg.strip(), "version": ver.strip(), "source": filename})
        cve_command = ["python3", "-m", "pip_audit", "--desc", "--strict", "-r", str(self.repo_root / "requirements.txt")] if (self.repo_root / "requirements.txt").exists() else None
        cve_output = self._run_command(cve_command) if cve_command else {"skipped": True, "reason": "no requirements.txt"}
        return ToolResult(tool="cve_lookup", output={"dependencies": findings, "cve_scan": cve_output})

    def _secret_scan(self, args: Dict[str, Any]) -> ToolResult:
        target = str(args.get("path", "."))
        search_root = self._resolve_path(target) if self.repo_root else Path(target).resolve()
        if not search_root.exists():
            return ToolResult(tool="secret_scan", output={"secrets_found": []})
        secrets: List[Dict[str, Any]] = []
        for path in search_root.rglob("*"):
            if not self._is_scannable_file(path) or path.suffix in {".pyc", ".png", ".jpg", ".gif", ".svg", ".lock"}:
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                continue
            try:
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    for pattern in SECRET_PATTERNS:
                        m = pattern.search(line)
                        if m:
                            secrets.append({
                                "path": str(path.relative_to(search_root)),
                                "line": lineno,
                                "pattern": pattern.pattern[:60],
                                "evidence": line[:120].strip(),
                            })
                            break
            except Exception:
                continue
        return ToolResult(tool="secret_scan", output={"secrets_found": secrets[:50]})

    def _check_auth_patterns(self, args: Dict[str, Any]) -> ToolResult:
        target = str(args.get("path", "."))
        search_root = self._resolve_path(target) if self.repo_root else Path(target).resolve()
        if not search_root.exists():
            return ToolResult(tool="check_auth_patterns", output={"auth_issues": []})
        auth_issues: List[Dict[str, Any]] = []
        AUTH_WEAK_PATTERNS: List[re.Pattern] = [
            re.compile(r"(?i)@app\.route.*login"),
            re.compile(r"(?i)def\s+login\b"),
            re.compile(r"(?i)(?:is_admin|is_authenticated|is_authorized)\s*=\s*True"),
            re.compile(r"(?i)request\.remote_addr"),
            re.compile(r"(?i)allow_any\s*=\s*True"),
            re.compile(r"(?i)authentication\s*=\s*None"),
        ]
        for path in search_root.rglob("*.py"):
            if not self._is_scannable_file(path):
                continue
            try:
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    for pat in AUTH_WEAK_PATTERNS:
                        if pat.search(line):
                            auth_issues.append({
                                "path": str(path.relative_to(search_root)),
                                "line": lineno,
                                "pattern": pat.pattern[:60],
                                "evidence": line[:120].strip(),
                            })
                            break
            except Exception:
                continue
        return ToolResult(tool="check_auth_patterns", output={"auth_issues": auth_issues[:30]})
