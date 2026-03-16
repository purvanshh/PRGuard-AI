"""Repository indexing utilities for PRGuard AI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from chromadb import Client
from chromadb.config import Settings


DEFAULT_COLLECTION = "prguard_repo_index"


def _create_chroma_client(persist_directory: str | None = ".chroma") -> Client:
    return Client(Settings(is_persistent=True, persist_directory=persist_directory))


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


__all__ = ["index_repository", "retrieve_similar_code", "DEFAULT_COLLECTION"]

