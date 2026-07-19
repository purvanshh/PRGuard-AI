import json

import pytest

from prguard_ai.llm.client import extract_json_from_llm_response, parse_agent_issues


def test_structured_output_parser_validates_issue_schema():
    raw = json.dumps(
        [
            {
                "line": 4,
                "severity": "HIGH",
                "message": "SQL injection",
                "evidence": "query + user_input",
                "confidence_source": "llm_reasoning",
            }
        ]
    )

    issues = parse_agent_issues(raw)

    assert issues[0].severity == "high"


def test_structured_output_rejects_text_wrapped_json():
    with pytest.raises(json.JSONDecodeError):
        extract_json_from_llm_response("Here are findings: []")
