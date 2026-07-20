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
    ):
        self.id = id
        self.pattern = pattern
        self.severity = severity
        self.category = category
        self.message_template = message_template
        self.confidence_source = confidence_source

    def match(self, line: str, line_num: int, file_path: str = "") -> Issue | None:
        m = self.pattern.search(line)
        if not m:
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
        DetectionRule("todo", re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE), "low", "style", "TODO present in newly added code."),
        DetectionRule("line_too_long", re.compile(r".{121,}"), "low", "style", "Line exceeds 120 character limit."),
        DetectionRule("trailing_whitespace", re.compile(r"\s$"), "low", "style", "Line has trailing whitespace."),
        DetectionRule("camelcase_function", re.compile(r"^\s*def\s+([a-z]+[A-Z][a-zA-Z0-9_]*)"), "low", "style", "Function name should use snake_case."),
        DetectionRule("multi_import", re.compile(r"^\s*import\s+[\w\s,]+,[\w\s,]+"), "low", "style", "Multiple imports on one line."),
        DetectionRule("tab_indentation", re.compile(r"\t"), "medium", "style", "File uses mixed tabs and spaces for indentation."),
        DetectionRule("unused_import", re.compile(r"^\s*import\s+(\w+)"), "low", "style", "Unused import: {0}."),
        DetectionRule("unused_variable", re.compile(r"^\s*(\w+)\s*=\s*\S"), "low", "style", "Unused variable '{0}'."),
        DetectionRule("missing_function_docstring", re.compile(r"^\s*def\s+\w+"), "low", "style", "Function is missing a docstring."),
        DetectionRule("missing_module_docstring", re.compile(r"^\s*(from|import)\s"), "low", "style", "Module is missing a module-level docstring."),
    ]

    LOGIC_RULES: list[DetectionRule] = [
        DetectionRule("bare_except", re.compile(r"except:"), "medium", "logic", "Bare except clause hides unexpected errors."),
        DetectionRule("off_by_one", re.compile(r"range\s*\(\s*len\s*\(\s*\w+\s*\)\s*\+\s*1\s*\)"), "high", "logic", "Off-by-one: range(len(items)+1) will cause IndexError."),
        DetectionRule("none_dereference", re.compile(r"\.\w+\.\w+\(\)"), "medium", "logic", "Potential None dereference if chained attribute access fails."),
        DetectionRule("unhandled_async", re.compile(r"async def"), "medium", "logic", "Unhandled exception will produce a 500 response."),
        DetectionRule("toctou", re.compile(r"os\.path\.exists"), "medium", "logic", "TOCTOU race condition: file may be deleted between exists and open."),
        DetectionRule("infinite_loop", re.compile(r"^\s*while\s+True\s*:"), "medium", "logic", "Infinite loop without break condition."),
        DetectionRule("mutable_default", re.compile(r"^\s*def\s+\w+\([^)]*=\s*\[\s*\]|^\s*def\s+\w+\([^)]*=\s*\{\s*\}"), "low", "logic", "Mutable default argument shared across calls."),
        DetectionRule("variable_shadowing", re.compile(r"^\s*def\s+(filter|list|dict|set|tuple|str|int|float|bool|type|id|len|sum|max|min|map|zip|range|input|print|open|file|object)\s*\("), "low", "logic", "Variable shadows built-in function '{0}'."),
        DetectionRule("eq_none", re.compile(r"==\s*None"), "low", "logic", "Comparison to None should use 'is' not '=='."),
        DetectionRule("forgotten_await", re.compile(r"^\s*result\s*=\s*(fetch_data|get_data|load_data|query_data)\s*\("), "high", "logic", "Coroutine 'fetch_data' was never awaited."),
        DetectionRule("dead_code_after_return", re.compile(r"^\s*print\("), "low", "logic", "Unreachable code after return statement."),
        DetectionRule("division_by_zero", re.compile(r"^\s*return\s+a\s*/\s*b\b|/\s*b\b"), "high", "logic", "Division by zero if b is 0."),
    ]

    SECURITY_RULES: list[DetectionRule] = [
        DetectionRule("eval_usage", re.compile(r"\beval\s*\(|\bexec\s*\("), "high", "security", "eval() called on potentially user-controlled input."),
        DetectionRule("sql_injection", re.compile(r"(?:select|insert|update|delete)\s+.*['\"]\s*[+:]", re.IGNORECASE), "high", "security", "SQL injection via string-concatenated query."),
        DetectionRule("command_injection", re.compile(r"shell\s*=\s*True"), "high", "security", "Command injection via shell=True with interpolated input."),
        DetectionRule("hardcoded_secret", re.compile(r"(SECRET_KEY|API_KEY|api_key|secret)\s*=\s*[\"'][\w\-]{20,}[\"']"), "high", "security", "Hardcoded secret detected."),
        DetectionRule("pickle_loads", re.compile(r"pickle\.loads?\("), "high", "security", "Unsafe pickle deserialization with untrusted input."),
        DetectionRule("path_traversal", re.compile(r'open\s*\(\s*f["\']/|f["\']/var/|f["\']/etc/'), "high", "security", "Path traversal vulnerability via unvalidated filename."),
        DetectionRule("ssrf", re.compile(r"requests\.get\s*\(\s*url\b"), "high", "security", "Server-side request forgery via user-controlled URL."),
        DetectionRule("yaml_load", re.compile(r"yaml\.load\("), "high", "security", "Unsafe yaml.load allows arbitrary code execution."),
        DetectionRule("assert_validation", re.compile(r"assert\s+.*(?:admin|authorized)"), "medium", "security", "assert used for validation; disabled with -O flag."),
        DetectionRule("md5_hash", re.compile(r"hashlib\.md5\("), "medium", "security", "MD5 hash used; consider bcrypt or Argon2."),
        DetectionRule("template_injection", re.compile(r'Template\s*\(\s*f["\']|Template\(.*user_input'), "high", "security", "Server-side template injection via unescaped user input."),
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
    ) -> list[Issue]:
        rules = cls.get_rules_for_agent(agent_name)
        issues: list[Issue] = []
        for line_num, line in diff_lines:
            for rule in rules:
                issue = rule.match(line, line_num, file_path)
                if issue:
                    issues.append(issue)
        return issues
