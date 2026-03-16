"""Repository indexing utilities for PRGuard AI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from chromadb import Client
from chromadb.config import Settings

from config.settings import settings


DEFAULT_COLLECTION = "prguard_repo_index"

_INDEX_INITIALIZED: bool = False


def _create_chroma_client(persist_directory: str | None = None) -> Client:
    persist_dir = persist_directory or settings.chroma_persist_dir
    return Client(Settings(is_persistent=True, persist_directory=persist_dir))


def index_repository(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    """
    Scan the repository and index functions/classes into ChromaDB for style retrieval.
    """
    root = Path(repo_path)
    client = _create_chroma_client()
    collection = client.get_or_create_collection(collection_name)

    documents: List[str] = []
    ids: List[str] = []
    metadatas: List[dict] = []

    idx = 0
    for path in root.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        documents.append(content)
        ids.append(f"{rel}:{idx}")
        metadatas.append({"path": rel})
        idx += 1

    if documents:
        collection.add(documents=documents, ids=ids, metadatas=metadatas)


def initialize_repo_index(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    """
    Ensure that a Chroma index for the repository exists and is populated.
    """
    global _INDEX_INITIALIZED
    if _INDEX_INITIALIZED:
        return

    client = _create_chroma_client()
    collection = client.get_or_create_collection(collection_name)
    existing = collection.count() if hasattr(collection, "count") else 0
    if not existing:
        index_repository(repo_path, collection_name=collection_name)
    _INDEX_INITIALIZED = True


def retrieve_similar_code(
    snippet: str,
    collection_name: str = DEFAULT_COLLECTION,
    n_results: int = 5,
) -> Iterable[Tuple[str, str]]:
    """
    Retrieve repository examples similar to the provided code snippet.

    Returns an iterable of (path, code_snippet) tuples.
    """
    client = _create_chroma_client()
    collection = client.get_or_create_collection(collection_name)
    result = collection.query(query_texts=[snippet], n_results=n_results)

    docs = result.get("documents") or [[]]
    metas = result.get("metadatas") or [[]]
    out: List[Tuple[str, str]] = []
    for doc, meta in zip(docs[0], metas[0]):
        path = meta.get("path", "")
        out.append((path, doc))
    return out


__all__ = ["index_repository", "initialize_repo_index", "retrieve_similar_code", "DEFAULT_COLLECTION"]

