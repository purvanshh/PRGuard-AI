"""Tests for the Semgrep JSON parser (Phase 4)."""

import json

import pytest

from prguard_ai.semgrep.parser import SemgrepFinding, findings_to_issues, parse_semgrep_json

SAMPLE_RESULT = {
    "check_id": "python.lang.security.audit.eval-usage",
    "path": "app.py",
    "start": {"line": 42, "col": 10},
    "end": {"line": 42, "col": 20},
    "extra": {
        "message": "Detected eval() on potentially user-controlled input",
        "severity": "ERROR",
        "lines": "result = eval(user_input)",
        "metadata": {
            "category": "security",
            "cwe": ["CWE-95: Improper Neutralization of Directives in Dynamically Evaluated Code"],
            "owasp": ["A03:2021 - Injection"],
        },
    },
}


def _payload(*results):
    return json.dumps({"results": list(results), "errors": []})


def test_parse_object_form_maps_severity():
    finding = parse_semgrep_json(_payload(SAMPLE_RESULT))[0]
    assert isinstance(finding, SemgrepFinding)
    assert finding.rule_id == "python.lang.security.audit.eval-usage"
    assert finding.severity == "high"
    assert finding.file_path == "app.py"
    assert finding.line == 42
    assert "eval" in finding.evidence
    assert finding.category == "security"
    assert finding.cwe[0].startswith("CWE-95")
    assert finding.owasp[0].startswith("A03")


def test_parse_bare_list_form():
    findings = parse_semgrep_json(json.dumps([SAMPLE_RESULT]))
    assert len(findings) == 1


def test_severity_mapping_table():
    severities = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    for raw, expected in severities.items():
        result = dict(SAMPLE_RESULT)
        result["extra"] = {**result["extra"], "severity": raw}
        assert parse_semgrep_json(_payload(result))[0].severity == expected


def test_ignored_findings_filtered_out():
    ignored = dict(SAMPLE_RESULT)
    ignored["extra"] = {**ignored["extra"], "is_ignored": True}
    assert parse_semgrep_json(_payload(ignored)) == []
    assert len(parse_semgrep_json(_payload(ignored, SAMPLE_RESULT))) == 1


def test_findings_to_issues_emits_semgrep_source():
    finding = parse_semgrep_json(_payload(SAMPLE_RESULT))[0]
    issues = findings_to_issues([finding])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.confidence_source == "semgrep"
    assert issue.verified is True
    assert issue.file_path == "app.py"
    assert issue.line == 42
    assert issue.message.startswith("[semgrep/python.lang.security.audit.eval-usage]")


def test_bad_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_semgrep_json("not json")
