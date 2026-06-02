"""Tests for AST summaries across supported languages."""

from __future__ import annotations

import pytest

from prguard_ai.analysis.ast_parser import summarize_source


@pytest.mark.parametrize(
    ("file_path", "source", "expected_function", "expected_control_type"),
    [
        (
            "main.py",
            "def greet(name):\n    if name:\n        return name\n    return 'anon'\n",
            "greet",
            "if_statement",
        ),
        (
            "main.go",
            "package main\nfunc greet(name string) string {\n    if name == \"\" {\n        return \"anon\"\n    }\n    return name\n}\n",
            "greet",
            "if_statement",
        ),
        (
            "main.ts",
            "function greet(name: string): string {\n  if (!name) {\n    return \"anon\";\n  }\n  return name;\n}\n",
            "greet",
            "if_statement",
        ),
        (
            "main.rs",
            "fn greet(name: &str) -> &str {\n    if name.is_empty() {\n        return \"anon\";\n    }\n    name\n}\n",
            "greet",
            "if_expression",
        ),
    ],
)
def test_summarize_source_supports_multiple_languages(
    file_path: str,
    source: str,
    expected_function: str,
    expected_control_type: str,
) -> None:
    summary = summarize_source(source, file_path=file_path)

    assert summary.language is not None
    assert any(function["name"] == expected_function for function in summary.functions)
    assert any(control["type"] == expected_control_type for control in summary.control_structures)


def test_summarize_source_returns_empty_summary_for_unsupported_language() -> None:
    summary = summarize_source("public class App {}\n", file_path="App.java")

    assert summary.language is None
    assert summary.functions == []
