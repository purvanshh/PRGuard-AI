"""Smoke tests for analysis agents."""

from pathlib import Path

import pytest

from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
from prguard_ai.agents import style_agent
from prguard_ai.agents.style_agent import analyze_style


DIFF = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
-old line
+new line
+long line with TODO that is very long and should likely trigger style issues because it exceeds the line limit and also includes TODO marker
+eval("print('unsafe')")
"""


def test_style_agent_runs():
    output = analyze_style(DIFF)
    assert output.agent == "style"
    assert 0.0 <= output.confidence <= 1.0
    assert output.reasoning_trace
    assert output.tool_calls


def test_logic_agent_runs():
    output = analyze_logic(DIFF)
    assert output.agent == "logic"
    assert 0.0 <= output.confidence <= 1.0
    assert output.reasoning_trace
    assert output.tool_calls


def test_security_agent_runs():
    output = analyze_security(DIFF)
    assert output.agent == "security"
    assert 0.0 <= output.confidence <= 1.0
    assert output.reasoning_trace
    assert output.tool_calls


def test_logic_agent_confidence_tracks_issue_strength():
    todo_diff = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,2 @@
-return 1
+return 1
+# TODO: handle edge case
"""

    except_diff = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,3 @@
-return 1
+try:
+    return 1
+except:
"""

    todo_output = analyze_logic(todo_diff)
    except_output = analyze_logic(except_diff)

    assert todo_output.confidence < except_output.confidence
    assert todo_output.confidence < 0.7


def test_context_lines_not_empty(tmp_path: Path):
    diff = """diff --git a/app/main.py b/app/main.py
index 111..222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,2 +1,3 @@
-def run():
-    return old
+def run():
+    value = compute()
+    return value
"""
    sandbox_root = tmp_path / "sandbox"
    file_path = sandbox_root / "app" / "main.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def run():\n    value = compute()\n    return value\n", encoding="utf-8")

    output = analyze_logic(
        diff,
        {"pr_id": "owner/repo#1", "sandbox_path": str(sandbox_root)},
    )

    assert output.agent == "logic"


def test_security_agent_confidence_tracks_issue_strength():
    clean_diff = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-return 1
+return 2
"""

    risky_diff = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,2 @@
-return 1
+user_input = payload
+eval(user_input)
"""

    clean_output = analyze_security(clean_diff)
    risky_output = analyze_security(risky_diff)

    assert clean_output.confidence < risky_output.confidence
    assert 0.8 <= risky_output.confidence < 0.95


def test_style_agent_flags_frontend_design_regression():
    diff = """diff --git a/app.css b/app.css
index 111..222 100644
--- a/app.css
+++ b/app.css
@@ -1,3 +1,5 @@
 .cta {
+  color: #ffffff;
+  background-color: #ffffff;
+  font-size: 10px;
 }
"""

    output = analyze_style(diff)

    messages = {issue.message for issue in output.issues}
    assert "Text color matches the background color, which can make content unreadable." in messages
    assert "Font size is very small and may hurt readability." in messages


def test_style_agent_attaches_file_path_to_llm_issues(monkeypatch: pytest.MonkeyPatch):
    diff = """diff --git a/app.css b/app.css
index 111..222 100644
--- a/app.css
+++ b/app.css
@@ -1,1 +1,2 @@
-.old { color: black; }
+.new { color: white; }
+button:focus { outline: none; }
"""

    def _fake_generate_analysis(*args, **kwargs):
        return (
            '[{"line": 2, "severity": "medium", "message": "Focus styling is inconsistent.", '
            '"evidence": "button:focus { outline: none; }", "confidence_source": "llm_reasoning"}]',
            {},
        )

    monkeypatch.setattr(style_agent, "generate_analysis", _fake_generate_analysis)

    output = analyze_style(diff)

    llm_issue = next(issue for issue in output.issues if issue.confidence_source == "llm_reasoning")
    assert llm_issue.file_path == "app.css"
