from prguard_ai.llm.client import generate_analysis
from prguard_ai.llm.model_router import ModelRouter, SemanticCache, semantic_cache


def test_model_router_loads_config_and_routes_by_complexity():
    router = ModelRouter.from_file("model_router.yaml")

    simple = router.route("style", "small lint diff")
    complex_route = router.route("security", "diff --git a/x b/x\n" + "auth sql token payment")

    assert simple.model == "gpt-4o-mini"
    assert complex_route.model == "gpt-4o"
    assert complex_route.max_tokens == 2048


def test_semantic_cache_matches_near_duplicate_prompt():
    cache = SemanticCache(threshold=0.5)
    cache.set("security: user input reaches sql query", "[{}]", {"model": "test"})

    result = cache.get("security: sql query receives user input")

    assert result is not None
    _, meta = result
    assert meta["cache_hit"] is True


def test_generate_analysis_uses_agent_route_and_cache(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "phase6")
    semantic_cache.clear()

    first_response, first_meta = generate_analysis("tiny lint prompt", agent="style")
    second_response, second_meta = generate_analysis("tiny lint prompt", agent="style")

    assert first_response == second_response == "[]"
    assert first_meta["model"] == "offline-stub"
    assert first_meta["route_complexity"] == "simple"
    assert second_meta["cache_hit"] is True
