"""Lightweight, cached code graph utilities for PRGuard AI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple


MAX_INDEXED_FILES = 500


@lru_cache(maxsize=16)
def build_code_graph(repo_path: str) -> Dict[str, Set[str]]:
    """
    Build a simple import-based dependency graph for a repository.

    The graph maps module file paths to the set of modules they import.
    Results are cached per repository path to avoid repeated work.
    """
    root = Path(repo_path)
    graph: Dict[str, Set[str]] = {}
    count = 0

    for path in root.rglob("*.py"):
        # Basic size limit to keep things manageable in large repos.
        if count >= MAX_INDEXED_FILES:
            break
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        rel = str(path.relative_to(root))
        imports: Set[str] = set()
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("import "):
                    parts = line.split()
                    if len(parts) >= 2:
                        imports.add(parts[1])
                elif line.startswith("from "):
                    parts = line.split()
                    if len(parts) >= 2:
                        imports.add(parts[1])
        except OSError:
            continue
        graph[rel] = imports
        count += 1

    return graph


__all__ = ["build_code_graph", "MAX_INDEXED_FILES"]

