"""Smoke tests for analysis agents."""

from prguard_ai.agents.logic_agent import analyze_logic
from prguard_ai.agents.security_agent import analyze_security
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


def test_logic_agent_runs():
    output = analyze_logic(DIFF)
    assert output.agent == "logic"
    assert 0.0 <= output.confidence <= 1.0


def test_security_agent_runs():
    output = analyze_security(DIFF)
    assert output.agent == "security"
    assert 0.0 <= output.confidence <= 1.0

