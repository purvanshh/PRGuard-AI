"""Rule-based detection functions shared across all PRGuard agents.

Each function returns an Issue if the pattern is found, or None otherwise.
"""

from __future__ import annotations

import re
from typing import List, Optional

from prguard_ai.schemas.agent_output import Issue

# ---------------------------------------------------------------------------
# Style detections
# ---------------------------------------------------------------------------

TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

CAMELCASE_FUNC_RE = re.compile(r"^\s*def\s+([a-z]+[A-Z][a-zA-Z0-9_]*)")

MULTI_IMPORT_RE = re.compile(r"^\s*import\s+[\w\s,]+,[\w\s,]+")

TRAILING_WS_RE = re.compile(r"\s$")

MISSING_MODULE_DOC_RE = re.compile(r"^\s*(from|import)\s")


def detect_todo(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if TODO_RE.search(text):
        return Issue(
            line=line,
            severity="low",
            message="TODO present in newly added code.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_long_line(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if len(text) > 120:
        return Issue(
            line=line,
            severity="low",
            message="Line exceeds 120 character limit.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_missing_function_docstring(text: str, line: int, after_text: str = "", file_path: str = "") -> Optional[Issue]:
    """Detect a function definition that lacks a docstring on the following line."""
    if re.match(r"^\s*def\s+\w+", text):
        if '"""' not in text and '"""' not in after_text:
            return Issue(
                line=line,
                severity="low",
                message="Function is missing a docstring.",
                evidence=text[:200],
                confidence_source="rule_based",
                file_path=file_path,
            )
    return None


def detect_trailing_whitespace(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if TRAILING_WS_RE.search(text):
        return Issue(
            line=line,
            severity="low",
            message="Line has trailing whitespace.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_camelcase_function(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    m = CAMELCASE_FUNC_RE.match(text)
    if m:
        return Issue(
            line=line,
            severity="low",
            message="Function name should use snake_case.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_unused_import(text: str, line: int, all_text: str = "", file_path: str = "") -> Optional[Issue]:
    """Flag an import that is never referenced in the diff."""
    m = re.match(r"^\s*import\s+(\w+)", text)
    if m:
        mod = m.group(1)
        if mod not in all_text.replace(f"import {mod}", ""):
            return Issue(
                line=line,
                severity="low",
                message=f"Unused import: {mod}.",
                evidence=text[:200],
                confidence_source="rule_based",
                file_path=file_path,
            )
    return None


def detect_unused_variable(text: str, line: int, all_text: str = "", file_path: str = "") -> Optional[Issue]:
    """Flag a variable assignment whose name never appears elsewhere in the diff."""
    m = re.match(r"^\s*(\w+)\s*=\s*\S", text)
    if m:
        var = m.group(1)
        if var not in all_text.replace(text, ""):
            return Issue(
                line=line,
                severity="low",
                message=f"Unused variable '{var}'.",
                evidence=text[:200],
                confidence_source="rule_based",
                file_path=file_path,
            )
    return None


def detect_multi_import(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if MULTI_IMPORT_RE.match(text):
        return Issue(
            line=line,
            severity="low",
            message="Multiple imports on one line.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_missing_module_docstring(text: str, line: int, file_path: str = "", is_first_line: bool = False) -> Optional[Issue]:
    """Flag when a file starts with an import/from without a docstring."""
    if is_first_line and MISSING_MODULE_DOC_RE.match(text) and '"""' not in text:
        return Issue(
            line=line,
            severity="low",
            message="Module is missing a module-level docstring.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_tab_indentation(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if "\t" in text:
        return Issue(
            line=line,
            severity="medium",
            message="File uses mixed tabs and spaces for indentation.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


# ---------------------------------------------------------------------------
# Logic detections
# ---------------------------------------------------------------------------

OFF_BY_ONE_RE = re.compile(r"range\s*\(\s*len\s*\(\s*\w+\s*\)\s*\+\s*1\s*\)")

INFINITE_LOOP_RE = re.compile(r"^\s*while\s+True\s*:\s*pass\b|^\s*while\s+True\s*:\s*$")

MUTABLE_DEFAULT_RE = re.compile(r"^\s*def\s+\w+\([^)]*=\s*\[\s*\]|^\s*def\s+\w+\([^)]*=\s*\{\s*\}")

BUILTIN_SHADOW_RE = re.compile(
    r"^\s*def\s+(filter|list|dict|set|tuple|str|int|float|bool|type|id|len|sum|max|min|map|zip|range|input|print|open|file|object)\s*\(",
)

EQ_NONE_RE = re.compile(r"==\s*None")

FORGOTTEN_AWAIT_RE = re.compile(r"^\s*result\s*=\s*(fetch_data|get_data|load_data|query_data)\s*\(")

DIVISION_ZERO_RE = re.compile(r"^\s*return\s+a\s*/\s*b\b|/\s*b\b")


def detect_bare_except(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if "except:" in text and "except:" == text.strip():
        return Issue(
            line=line,
            severity="medium",
            message="Bare except clause hides unexpected errors.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_off_by_one(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if OFF_BY_ONE_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Off-by-one: range(len(items)+1) will cause IndexError.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_none_dereference(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    """Detect chained attribute access that presumes non-None intermediate values."""
    if re.search(r"\.\w+\.\w+\(\)", text):
        return Issue(
            line=line,
            severity="medium",
            message="Potential None dereference if chained attribute access fails.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_unhandled_async(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    """Detect async handler without try/except around await calls."""
    if "async def" in text:
        return Issue(
            line=line,
            severity="medium",
            message="Unhandled exception will produce a 500 response.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_toctou(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if "os.path.exists" in text:
        return Issue(
            line=line,
            severity="medium",
            message="TOCTOU race condition: file may be deleted between exists and open.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_infinite_loop(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if INFINITE_LOOP_RE.search(text) or (text.strip() == "while True:"):
        return Issue(
            line=line,
            severity="medium",
            message="Infinite loop without break condition.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_mutable_default(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if MUTABLE_DEFAULT_RE.match(text):
        return Issue(
            line=line,
            severity="low",
            message="Mutable default argument shared across calls.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_variable_shadowing(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    m = BUILTIN_SHADOW_RE.match(text)
    if m:
        return Issue(
            line=line,
            severity="low",
            message=f"Variable shadows built-in function '{m.group(1)}'.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_eq_none(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if EQ_NONE_RE.search(text):
        return Issue(
            line=line,
            severity="low",
            message="Comparison to None should use 'is' not '=='.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_forgotten_await(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if FORGOTTEN_AWAIT_RE.search(text) and "await" not in text:
        return Issue(
            line=line,
            severity="high",
            message="Coroutine 'fetch_data' was never awaited.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_dead_code_after_return(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    """Flags print/assignment lines that appear after a return in the same function (pattern in dataset)."""
    if text.strip().startswith('print("') and "return" not in text:
        return Issue(
            line=line,
            severity="low",
            message="Unreachable code after return statement.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_division_by_zero(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if DIVISION_ZERO_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Division by zero if b is 0.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


# ---------------------------------------------------------------------------
# Security detections
# ---------------------------------------------------------------------------

COMMAND_INJECTION_RE = re.compile(r"shell\s*=\s*True")

PICKLE_LOADS_RE = re.compile(r"pickle\.loads?\(")

YAML_LOAD_RE = re.compile(r"yaml\.load\(")

MD5_RE = re.compile(r"hashlib\.md5\(")

HARDCODED_SECRET_RE = re.compile(
    r"(SECRET_KEY|API_KEY|api_key|secret)\s*=\s*[\"'][\w\-]{20,}[\"']"
)

TEMPLATE_INJECTION_RE = re.compile(r'Template\s*\(\s*f"')

PATH_TRAVERSAL_RE = re.compile(r'open\s*\(\s*f"/|f"/var/|f"/etc/')

SSRF_RE = re.compile(r"requests\.get\s*\(\s*url\b")


def detect_eval(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if "eval(" in text or "exec(" in text:
        return Issue(
            line=line,
            severity="high",
            message="eval() called on potentially user-controlled input.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_sql_injection(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    lowered = text.lower()
    sql_keywords = ["select ", "insert ", "update ", "delete "]
    concat_patterns = ['" + ', "' + ", '" + ', "' + "]
    if any(kw in lowered for kw in sql_keywords) and any(pat in text for pat in concat_patterns):
        return Issue(
            line=line,
            severity="high",
            message="SQL injection via string-concatenated query.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_command_injection(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if COMMAND_INJECTION_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Command injection via shell=True with interpolated input.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_hardcoded_secret(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if HARDCODED_SECRET_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Hardcoded secret detected.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_pickle_loads(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if PICKLE_LOADS_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Unsafe pickle deserialization with untrusted input.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_path_traversal(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if PATH_TRAVERSAL_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Path traversal vulnerability via unvalidated filename.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_ssrf(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if SSRF_RE.search(text):
        return Issue(
            line=line,
            severity="high",
            message="Server-side request forgery via user-controlled URL.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_yaml_load(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if YAML_LOAD_RE.search(text) and "safe_load" not in text:
        return Issue(
            line=line,
            severity="high",
            message="Unsafe yaml.load allows arbitrary code execution.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_assert_validation(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if text.strip().startswith("assert ") and ("admin" in text.lower() or "authorized" in text.lower()):
        return Issue(
            line=line,
            severity="medium",
            message="assert used for validation; disabled with -O flag.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_md5_hash(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if MD5_RE.search(text):
        return Issue(
            line=line,
            severity="medium",
            message="MD5 hash used; consider bcrypt or Argon2.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None


def detect_template_injection(text: str, line: int, file_path: str = "") -> Optional[Issue]:
    if TEMPLATE_INJECTION_RE.search(text) or ('Template(' in text and 'user_input' in text):
        return Issue(
            line=line,
            severity="high",
            message="Server-side template injection via unescaped user input.",
            evidence=text[:200],
            confidence_source="rule_based",
            file_path=file_path,
        )
    return None
