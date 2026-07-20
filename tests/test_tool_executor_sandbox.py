"""Tests for repository sandbox enforcement in agent tools."""

from prguard_ai.agents.tools import AgentToolExecutor, ToolInvocation


def invoke(executor: AgentToolExecutor, tool: str, **args):
    return executor.execute(ToolInvocation(tool=tool, args=args))


def test_read_file_rejects_parent_traversal(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read me", encoding="utf-8")

    executor = AgentToolExecutor({"sandbox_path": str(repo)})
    result = invoke(executor, "read_file", path="../secret.txt")

    assert result.ok is False
    assert "escapes repository sandbox" in result.error


def test_read_file_rejects_absolute_path_outside_sandbox(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")

    executor = AgentToolExecutor({"sandbox_path": str(repo)})
    result = invoke(executor, "read_file", path=str(outside))

    assert result.ok is False
    assert "escapes repository sandbox" in result.error


def test_read_file_allows_repo_relative_path(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('inside')\n", encoding="utf-8")

    executor = AgentToolExecutor({"sandbox_path": str(repo)})
    result = invoke(executor, "read_file", path="src/app.py")

    assert result.ok is True
    assert result.output["content"] == "print('inside')"


def test_run_test_rejects_parent_traversal(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tests = repo / "tests"
    tests.mkdir()

    executor = AgentToolExecutor({"sandbox_path": str(repo)})
    result = invoke(executor, "run_test", target="../tests")

    assert result.ok is False
    assert "escapes repository sandbox" in result.error


def test_search_codebase_skips_symlink_escape(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("API_TOKEN = 'outside-secret-token-12345'\n", encoding="utf-8")
    (repo / "inside.py").write_text("API_TOKEN = 'inside-only'\n", encoding="utf-8")
    (repo / "linked.py").symlink_to(outside)

    executor = AgentToolExecutor({"sandbox_path": str(repo)})
    result = invoke(executor, "search_codebase", query="API_TOKEN", limit=10)

    assert result.ok is True
    assert [match["path"] for match in result.output] == ["inside.py"]
