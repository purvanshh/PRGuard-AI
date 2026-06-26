from __future__ import annotations

import pytest
from pathlib import Path
from prguard_ai.analysis.code_graph import build_code_graph, MAX_INDEXED_FILES


def test_build_code_graph(tmp_path: Path):
    # Clear lru cache of build_code_graph to ensure fresh runs in test
    build_code_graph.cache_clear()

    # Create dummy python files
    repo = tmp_path / "my_repo"
    repo.mkdir()

    # File 1: module_a.py
    file_a = repo / "module_a.py"
    file_a.write_text(
        "import os\n"
        "from sys import argv\n"
        "def main():\n"
        "    pass\n",
        encoding="utf-8"
    )

    # File 2: module_b.py
    file_b = repo / "module_b.py"
    file_b.write_text(
        "import module_a\n"
        "from prguard_ai.llm import client\n",
        encoding="utf-8"
    )

    # File 3: in tests directory (should be ignored)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    file_c = tests_dir / "test_a.py"
    file_c.write_text("import pytest\n", encoding="utf-8")

    # File 4: in venv directory (should be ignored)
    venv_dir = repo / ".venv"
    venv_dir.mkdir()
    file_d = venv_dir / "lib.py"
    file_d.write_text("import sys\n", encoding="utf-8")

    graph = build_code_graph(str(repo))

    assert "module_a.py" in graph
    assert "module_b.py" in graph
    assert "tests/test_a.py" not in graph
    assert ".venv/lib.py" not in graph

    assert graph["module_a.py"] == {"os", "sys"}
    assert graph["module_b.py"] == {"module_a", "prguard_ai.llm"}


def test_build_code_graph_max_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    build_code_graph.cache_clear()
    
    # Override MAX_INDEXED_FILES to 2
    monkeypatch.setattr("prguard_ai.analysis.code_graph.MAX_INDEXED_FILES", 2)
    
    repo = tmp_path / "small_repo"
    repo.mkdir()
    
    for i in range(5):
        f = repo / f"file_{i}.py"
        f.write_text("import sys", encoding="utf-8")
        
    graph = build_code_graph(str(repo))
    # Should stop after indexing 2 files
    assert len(graph) == 2


def test_build_code_graph_os_error(tmp_path: Path):
    build_code_graph.cache_clear()
    
    repo = tmp_path / "err_repo"
    repo.mkdir()
    
    # Create directory structure, but we will make a file unreadable
    f = repo / "unreadable.py"
    f.mkdir()  # Making it a directory causes OSError when read_text is called on it
    
    graph = build_code_graph(str(repo))
    # Should skip unreadable.py without crashing
    assert "unreadable.py" not in graph
