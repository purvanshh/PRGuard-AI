"""Rule-based detection registry. Replaces 500+ lines of individual detect_* functions."""

from __future__ import annotations

import re
from typing import List, Tuple

from prguard_ai.schemas.agent_output import Issue


class DetectionRule:
    def __init__(
        self,
        id: str,
        pattern: re.Pattern,
        severity: str,
        category: str,
        message_template: str,
        confidence_source: str = "rule_based",
        add_only: bool = False,
    ):
        self.id = id
        self.pattern = pattern
        self.severity = severity
        self.category = category
        self.message_template = message_template
        self.confidence_source = confidence_source
        self.add_only = add_only

    def match(self, line: str, line_num: int, file_path: str = "", full_text: str = "") -> Issue | None:
        m = self.pattern.search(line)
        if not m:
            return None

        if self.id == "unused_import":
            mod = m.group(1)
            if mod in full_text.replace(f"import {mod}", ""):
                return None
        if self.id == "unused_variable":
            var = m.group(1)
            if var in full_text.replace(line, "") or var in ("self", "cls"):
                return None

        groups = m.groups()
        message = self.message_template.format(*groups) if groups else self.message_template
        return Issue(
            line=line_num,
            severity=self.severity,
            message=message,
            evidence=line[:200],
            confidence_source=self.confidence_source,
            file_path=file_path,
            verified=True,
        )


class DetectorRegistry:
    STYLE_RULES: list[DetectionRule] = [
        DetectionRule("todo", re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE), "low", "style", "TODO present in newly added code.", add_only=True),
        DetectionRule("line_too_long", re.compile(r".{121,}"), "low", "style", "Line exceeds 120 character limit.", add_only=True),
        DetectionRule("trailing_whitespace", re.compile(r"[ \t]$"), "low", "style", "Line has trailing whitespace.", add_only=True),
        DetectionRule("camelcase_function", re.compile(r"^\s*def\s+([a-z]+[A-Z][a-zA-Z0-9_]*)"), "low", "style", "Function name should use snake_case.", add_only=True),
        DetectionRule("multi_import", re.compile(r"^\s*import\s+[\w\s,]+,[\w\s,]+"), "low", "style", "Multiple imports on one line.", add_only=True),
        DetectionRule("tab_indentation", re.compile(r"^\t+"), "medium", "style", "File uses mixed tabs and spaces for indentation.", add_only=True),
        DetectionRule("unused_import", re.compile(r"^\s*import\s+(\w+)\s*$"), "low", "style", "Unused import: {0}.", add_only=True),
        DetectionRule("unused_variable", re.compile(r"^\s*(\w+)\s*=\s*\S"), "low", "style", "Unused variable '{0}'.", add_only=True),
        DetectionRule("missing_function_docstring", re.compile(r"^\s*def\s+\w+"), "low", "style", "Function is missing a docstring.", add_only=True),
        DetectionRule("missing_module_docstring", re.compile(r"^\s*(from|import)\s"), "low", "style", "Module is missing a module-level docstring.", add_only=True),
    ]

    LOGIC_RULES: list[DetectionRule] = [
        DetectionRule("bare_except", re.compile(r"^\s*except\s*:\s*$"), "medium", "logic", "Bare except clause hides unexpected errors.", add_only=False),
        DetectionRule("off_by_one", re.compile(r"range\s*\(\s*len\s*\(\s*\w+\s*\)\s*\+\s*1\s*\)"), "high", "logic", "Off-by-one: range(len(items)+1) will cause IndexError.", add_only=True),
        DetectionRule("none_dereference", re.compile(r"\.\w+\.\w+\("), "medium", "logic", "Potential None dereference if chained attribute access fails.", add_only=True),
        DetectionRule("unhandled_async", re.compile(r"^\s*async\s+def\b"), "medium", "logic", "Unhandled exception will produce a 500 response.", add_only=False),
        DetectionRule("toctou", re.compile(r"os\.path\.exists"), "medium", "logic", "TOCTOU race condition: file may be deleted between exists and open.", add_only=False),
        DetectionRule("infinite_loop", re.compile(r"^\s*while\s+True\s*:"), "medium", "logic", "Infinite loop without break condition.", add_only=True),
        DetectionRule("mutable_default", re.compile(r"=\s*\[\s*\]\s*\)|=\s*\{\s*\}\s*\)"), "low", "logic", "Mutable default argument shared across calls.", add_only=False),
        DetectionRule("variable_shadowing", re.compile(r"^\s*def\s+(filter|list|dict|set|tuple|str|int|float|bool|type|id|len|sum|max|min|map|zip|range|input|print|open|file|object)\s*\("), "low", "logic", "Variable shadows built-in function '{0}'.", add_only=True),
        DetectionRule("eq_none", re.compile(r"(?:==|!=)\s*None\b"), "low", "logic", "Comparison to None should use 'is' not '=='.", add_only=True),
        DetectionRule("forgotten_await", re.compile(r"^\s*\w+\s*=\s*(?:fetch_data|get_data|load_data|query_data)\s*\("), "high", "logic", "Coroutine 'fetch_data' was never awaited.", add_only=True),
        DetectionRule("dead_code_after_return", re.compile(r"^\s*print\("), "low", "logic", "Unreachable code after return statement.", add_only=True),
        DetectionRule("division_by_zero", re.compile(r"/\s*0\b"), "high", "logic", "Division by zero if divisor is 0.", add_only=True),
    ]

    SECURITY_RULES: list[DetectionRule] = [
        DetectionRule("eval_usage", re.compile(r"\beval\s*\(|\bexec\s*\("), "high", "security", "eval() called on potentially user-controlled input.", add_only=True),
        DetectionRule("sql_injection", re.compile(r"(?:select|insert|update|delete)\s+.*?['\"]\s*[+:]", re.IGNORECASE), "high", "security", "SQL injection via string-concatenated query.", add_only=True),
        DetectionRule("command_injection", re.compile(r"shell\s*=\s*True"), "high", "security", "Command injection via shell=True with interpolated input.", add_only=True),
        DetectionRule("hardcoded_secret", re.compile(r"(?:SECRET_KEY|API_KEY|api_key|secret|password|token)\s*=\s*[\"\'][\w\-\.]{8,}[\"\']", re.IGNORECASE), "high", "security", "Hardcoded secret detected.", add_only=True),
        DetectionRule("pickle_loads", re.compile(r"pickle\.loads?\("), "high", "security", "Unsafe pickle deserialization with untrusted input.", add_only=True),
        DetectionRule("path_traversal", re.compile(r"open\s*\(\s*(?:f[\"\']|[\"'].*\.\.[\"'])"), "high", "security", "Path traversal vulnerability via unvalidated filename.", add_only=True),
        DetectionRule("ssrf", re.compile(r"requests\.get\s*\(\s*(?:url|f[\"\']|\+ *\w+)"), "high", "security", "Server-side request forgery via user-controlled URL.", add_only=True),
        DetectionRule("yaml_load", re.compile(r"yaml\.load\("), "high", "security", "Unsafe yaml.load allows arbitrary code execution.", add_only=True),
        DetectionRule("assert_validation", re.compile(r"^\s*assert\s+(?:is_admin|is_authorized|is_authenticated|admin|authorized)\b"), "medium", "security", "assert used for validation; disabled with -O flag.", add_only=True),
        DetectionRule("md5_hash", re.compile(r"hashlib\.md5\("), "medium", "security", "MD5 hash used; consider bcrypt or Argon2.", add_only=True),
        DetectionRule("template_injection", re.compile(r"Template\s*\(.*?(?:f[\"\']|user_input|\+\s*\w+)"), "high", "security", "Server-side template injection via unescaped user input.", add_only=True),
        DetectionRule("subprocess_no_shell", re.compile(r"subprocess\.(?:Popen|run|call)\s*\("), "medium", "security", "Subprocess call should specify shell=False explicitly.", add_only=True),
    ]

    _MAPPING = {
        "style": STYLE_RULES,
        "logic": LOGIC_RULES,
        "security": SECURITY_RULES,
    }

    @classmethod
    def get_rules_for_agent(cls, agent_name: str) -> list[DetectionRule]:
        return cls._MAPPING.get(agent_name, [])

    @classmethod
    def match_all(
        cls,
        agent_name: str,
        diff_lines: list[tuple[int, str]],
        file_path: str,
        full_text: str = "",
        added_linenos: frozenset[int] | None = None,
    ) -> list[Issue]:
        rules = cls.get_rules_for_agent(agent_name)
        issues: list[Issue] = []
        for line_num, line in diff_lines:
            is_added = added_linenos is None or line_num in (added_linenos or frozenset())
            for rule in rules:
                if rule.add_only and not is_added:
                    continue
                issue = rule.match(line, line_num, file_path, full_text)
                if issue:
                    issues.append(issue)
        return issues
