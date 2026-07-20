import json

import pytest

from prguard_ai.llm.client import LLMClient, LLMIssueResponse, parse_agent_issues
from prguard_ai.schemas.agent_output import Issue


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


def test_structured_output_returns_parsed_model():
    from unittest.mock import MagicMock, patch

    client = LLMClient()

    mock_response = MagicMock()
    mock_response.choices[0].message.parsed = LLMIssueResponse(
        issues=[Issue(line=10, severity="high", message="test", evidence="x", confidence_source="llm_reasoning")]
    )

    with patch.object(client, '_get_client') as mock_get:
        mock_get.return_value.beta.chat.completions.parse.return_value = mock_response

        result = client.generate_analysis("test prompt", LLMIssueResponse)
        assert isinstance(result, LLMIssueResponse)
        assert len(result.issues) == 1


def test_no_regex_fallback_in_happy_path():
    from unittest.mock import MagicMock, patch

    client = LLMClient()

    with patch.object(client, '_get_client') as mock_get:
        mock_response = MagicMock()
        mock_response.choices[0].message.parsed = LLMIssueResponse(issues=[])
        mock_get.return_value.beta.chat.completions.parse.return_value = mock_response

        result = client.generate_analysis("test", LLMIssueResponse)

        mock_get.return_value.chat.completions.create.assert_not_called()


def test_malformed_json_fails_gracefully():
    from unittest.mock import MagicMock, patch
    from prguard_ai.llm.client import LLMOutputError

    client = LLMClient()

    with patch.object(client, '_get_client') as mock_get:
        mock_get.return_value.beta.chat.completions.parse.side_effect = Exception("Bad JSON")
        mock_get.return_value.chat.completions.create.side_effect = Exception("Also bad")

        with pytest.raises(LLMOutputError):
            client.generate_analysis("test", LLMIssueResponse)
