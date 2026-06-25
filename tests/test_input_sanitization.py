from __future__ import annotations

import pytest
from pydantic import ValidationError
from prguard_ai.schemas.agent_output import Issue, AgentOutput
from prguard_ai.agents.style_agent import _parse_llm_issues as style_parse
from prguard_ai.agents.logic_agent import _parse_llm_issues as logic_parse
from prguard_ai.agents.security_agent import _parse_llm_issues as security_parse
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent
from prguard_ai.schemas.context import ReviewContext


def test_issue_validation_and_sanitization():
    """Verify Issue.validate_and_sanitize validates, strips non-printable chars, and escapes HTML."""
    # Valid dict input
    valid_dict = {
        "line": 15,
        "severity": "High",
        "message": "Dangerous <b>script</b> usage \x00 detected.",
        "evidence": "eval(\"unsafe\"); & more",
        "confidence_source": "llm_reasoning",
    }

    issue = Issue.validate_and_sanitize(valid_dict)
    assert isinstance(issue, Issue)
    assert issue.line == 15
    assert issue.severity == "high"  # normalized to lowercase
    # HTML must be escaped: <b> -> &lt;b&gt;, </b> -> &lt;/b&gt;
    # Non-printable chars like \x00 should be stripped
    assert issue.message == "Dangerous &lt;b&gt;script&lt;/b&gt; usage  detected."
    # & must be escaped -> &amp;
    assert issue.evidence == "eval(&quot;unsafe&quot;); &amp; more"
    assert issue.confidence_source == "llm_reasoning"


def test_issue_validation_invalid_type():
    """Verify validate_and_sanitize raises ValidationError or TypeError for invalid values."""
    # Missing required field line
    invalid_dict = {
        "severity": "medium",
        "message": "No line",
        "evidence": "print()",
        "confidence_source": "rule_based"
    }
    with pytest.raises(ValidationError):
        Issue.validate_and_sanitize(invalid_dict)

    # Invalid type for input
    with pytest.raises(TypeError):
        Issue.validate_and_sanitize("just a string")


def test_issue_limit_style_agent():
    """Verify style agent limits the parsed LLM issues to 20."""
    # Create mock response containing 25 issues
    issues_data = []
    for i in range(1, 26):
        issues_data.append({
            "line": i,
            "severity": "low",
            "message": f"Issue number {i}",
            "evidence": "code",
            "confidence_source": "llm_reasoning"
        })
    
    import json
    raw_response = json.dumps(issues_data)
    
    parsed_issues = style_parse(raw_response)
    assert len(parsed_issues) == 20
    assert parsed_issues[-1].line == 20  # issue 21 onwards skipped


def test_issue_limit_logic_agent():
    """Verify logic agent limits the parsed LLM issues to 20."""
    issues_data = []
    for i in range(1, 26):
        issues_data.append({
            "line": i,
            "severity": "medium",
            "message": f"Logic bug {i}",
            "evidence": "code",
            "confidence_source": "llm_reasoning"
        })
    import json
    raw_response = json.dumps(issues_data)
    parsed_issues = logic_parse(raw_response)
    assert len(parsed_issues) == 20


def test_issue_limit_security_agent():
    """Verify security agent limits the parsed LLM issues to 20."""
    issues_data = []
    for i in range(1, 26):
        issues_data.append({
            "line": i,
            "severity": "high",
            "message": f"Security flaw {i}",
            "evidence": "code",
            "confidence_source": "llm_reasoning"
        })
    import json
    raw_response = json.dumps(issues_data)
    parsed_issues = security_parse(raw_response)
    assert len(parsed_issues) == 20


def test_refinement_issue_limit_style_agent(monkeypatch):
    """Verify style agent refinement limits issues to 20."""
    initial_output = AgentOutput(agent="style", confidence=0.5, issues=[])
    
    issues_data = []
    for i in range(1, 26):
        issues_data.append({
            "line": i,
            "severity": "low",
            "message": f"Refined style {i}",
            "evidence": "code",
            "confidence_source": "refined",
            "file_path": "foo.py"
        })
    
    mocked_response = {
        "message": "Refined list",
        "issues": issues_data
    }
    
    import json
    def _mock_gen(prompt, *args, **kwargs):
        return json.dumps(mocked_response), {}
        
    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", _mock_gen)
    
    context = ReviewContext(
        pr_id="test#1",
        diff_text="diff --git a/foo.py b/foo.py\n+line",
        agent_outputs={"style": initial_output}
    )
    
    msg, refined = StyleAgent.refine(initial_output, context)
    assert len(refined.issues) == 20
