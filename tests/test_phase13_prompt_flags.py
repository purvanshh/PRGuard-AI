from prguard_ai.config.feature_flags import canary_stage, is_enabled, rollout_enabled
from prguard_ai.prompts import load_prompt, prompt_path


def test_feature_flag_rollout(monkeypatch):
    monkeypatch.setenv("PRGUARD_FLAG_NEW_AGENT", "true")
    monkeypatch.setenv("PRGUARD_FLAG_AGENT_V2_ROLLOUT_PERCENT", "100")

    assert is_enabled("new_agent")
    assert rollout_enabled("agent_v2", "owner/repo#1")


def test_canary_deployment_stage(monkeypatch):
    monkeypatch.setenv("PRGUARD_FLAG_MODEL_CANARY_CANARY_STAGE", "25")
    assert canary_stage("model_canary", "owner/repo#1") == 25


def test_prompt_version_selection_loads_git_tracked_prompts(monkeypatch):
    monkeypatch.setenv("PRGUARD_PROMPT_VERSION", "v2")
    prompt, version = load_prompt("style")

    assert version == "v2"
    assert "style reviewer v2" in prompt
    assert prompt_path("style", "v1").exists()
