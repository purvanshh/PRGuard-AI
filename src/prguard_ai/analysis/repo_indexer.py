"""Repository indexing utilities for PRGuard AI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple


DEFAULT_COLLECTION = "prguard_repo_index"

def _create_chroma_client(*args, **kwargs):
    """
    Placeholder factory used when ChromaDB is not available.

    In this lightweight test configuration we disable persistent style indexing,
    so this function intentionally does nothing.
    """
    raise RuntimeError("ChromaDB client is disabled in this environment.")


def index_repository(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    """
    Scan the repository and index functions/classes into ChromaDB for style retrieval.
    """
    # In the no-Chroma test setup we skip building a persistent index.
    return None


def initialize_repo_index(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    """
    Ensure that a Chroma index for the repository exists and is populated.
    """
    # No-op when ChromaDB is disabled.
    return None


def retrieve_similar_code(
    snippet: str,
    collection_name: str = DEFAULT_COLLECTION,
    n_results: int = 5,
) -> Iterable[Tuple[str, str]]:
    """
    Retrieve repository examples similar to the provided code snippet.

    Returns an iterable of (path, code_snippet) tuples.
    """
    # Without ChromaDB we simply return no examples. The style agent
    # will still run, but without repository style retrieval.
    return []


__all__ = ["index_repository", "initialize_repo_index", "retrieve_similar_code", "DEFAULT_COLLECTION"]
