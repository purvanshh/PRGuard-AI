"""Tests for detector abstraction (Phase 9)."""

import re
import inspect

import pytest

from prguard_ai.analysis.detectors import DetectionRule, DetectorRegistry


def test_detector_registry_reduces_code():
    source = inspect.getsource(DetectorRegistry)
    lines = source.split('\n')
    assert len(lines) < 150


def test_all_rules_have_unique_ids():
    all_rules = (
        DetectorRegistry.STYLE_RULES
        + DetectorRegistry.LOGIC_RULES
        + DetectorRegistry.SECURITY_RULES
    )
    ids = [r.id for r in all_rules]
    assert len(ids) == len(set(ids))


def test_sql_injection_detected():
    lines = [(10, 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)')]
    issues = DetectorRegistry.match_all("security", lines, "app.py")
    assert len(issues) == 1
    assert issues[0].severity == "high"
    assert "SQL injection" in issues[0].message


def test_new_rule_no_code_changes():
    new_rule = DetectionRule(
        id="test_rule",
        pattern=re.compile(r'test'),
        severity="low",
        category="test",
        message_template="Test rule matched.",
    )
    DetectorRegistry.STYLE_RULES.append(new_rule)

    lines = [(1, "this is a test")]
    issues = DetectorRegistry.match_all("style", lines, "test.py")
    assert any("Test rule matched" in i.message for i in issues)

    DetectorRegistry.STYLE_RULES.remove(new_rule)


def test_style_rules_detect_todo():
    lines = [(5, "# TODO: fix this")]
    issues = DetectorRegistry.match_all("style", lines, "app.py")
    assert any("TODO" in i.message for i in issues)


def test_security_rules_detect_hardcoded_secret():
    lines = [(8, 'SECRET_KEY = "my-secret-key-1234567890"')]
    issues = DetectorRegistry.match_all("security", lines, "app.py")
    assert any("Hardcoded secret" in i.message for i in issues)


def test_logic_rules_detect_bare_except():
    lines = [(12, "except:")]
    issues = DetectorRegistry.match_all("logic", lines, "app.py")
    assert any("Bare except" in i.message for i in issues)
