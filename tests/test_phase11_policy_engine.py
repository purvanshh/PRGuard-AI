from prguard_ai.agents.style_agent import analyze_style
from prguard_ai.policy.engine import (
    PolicyConfig,
    apply_policy_to_issues,
    filter_diff_by_policy,
    merge_policies,
    parse_policy_text,
)
from prguard_ai.schemas.agent_output import Issue


def test_prguard_yml_parser_supports_repo_rules():
    policy = parse_policy_text(
        """
        severity_threshold: medium
        ignored_paths:
          - tests/**
          - docs/**
        required_reviewers: [security-team, platform-team]
        critical_paths:
          - src/payments/**
        severity_overrides:
          src/auth/**: high
        """
    )

    assert policy.severity_threshold == "medium"
    assert policy.is_ignored("tests/test_api.py")
    assert policy.required_reviewers == ["security-team", "platform-team"]
    assert policy.override_for_path("src/payments/charge.py") == "critical"
    assert policy.override_for_path("src/auth/login.py") == "high"


def test_policy_inheritance_repo_overrides_org_defaults():
    org = PolicyConfig(severity_threshold="medium", ignored_paths=["docs/**"], required_reviewers=["platform"])
    repo = PolicyConfig(ignored_paths=["tests/**"], critical_paths=["src/payments/**"])

    effective = merge_policies(org, repo)

    assert effective.severity_threshold == "medium"
    assert effective.ignored_paths == ["tests/**"]
    assert effective.required_reviewers == ["platform"]
    assert effective.critical_paths == ["src/payments/**"]


def test_custom_policy_enforced_on_issues_and_diff():
    policy = PolicyConfig(severity_threshold="medium", ignored_paths=["tests/**"], critical_paths=["src/payments/**"])
    issues = [
        Issue(line=1, severity="low", message="too long", evidence="x", confidence_source="rule_based", file_path="src/app.py"),
        Issue(line=2, severity="medium", message="tab", evidence="x", confidence_source="rule_based", file_path="tests/test_app.py"),
        Issue(line=3, severity="medium", message="risk", evidence="x", confidence_source="rule_based", file_path="src/payments/pay.py"),
    ]

    filtered = apply_policy_to_issues(issues, policy)

    assert len(filtered) == 1
    assert filtered[0].file_path == "src/payments/pay.py"
    assert filtered[0].severity == "critical"


def test_agents_skip_ignored_paths_before_analysis(monkeypatch):
    monkeypatch.setattr("prguard_ai.agents.style_agent.generate_analysis", lambda *args, **kwargs: ("[]", {}))
    diff = """diff --git a/tests/test_ui.py b/tests/test_ui.py
--- a/tests/test_ui.py
+++ b/tests/test_ui.py
@@ -1,1 +1,1 @@
+\tprint('style issue')
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,1 @@
+\tprint('style issue')
"""

    trimmed = filter_diff_by_policy(diff, PolicyConfig(ignored_paths=["tests/**"]))
    assert "tests/test_ui.py" not in trimmed
    assert "src/app.py" in trimmed

    output = analyze_style(diff, {"policy": {"ignored_paths": ["tests/**"]}})
    assert [issue.file_path for issue in output.issues] == ["src/app.py"]
