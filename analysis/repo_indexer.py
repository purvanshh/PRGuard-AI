"""Repository indexing utilities for PRGuard AI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from chromadb import Client
from chromadb.config import Settings


def create_chroma_client(persist_directory: str | None = None) -> Client:
    """
    Create a ChromaDB client configured for local persistence.

    Args:
        persist_directory: Optional directory for ChromaDB persistence.

    Returns:
        Configured ChromaDB client.
    """
    return Client(Settings(is_persistent=bool(persist_directory), persist_directory=persist_directory))


def index_repository_source_files(
    root: str | Path,
    collection_name: str,
    client: Client | None = None,
) -> None:
    """
    Index repository source files into ChromaDB.

    This is a minimal placeholder that stores file-level documents only.
    """
    root_path = Path(root)
    if client is None:
        client = create_chroma_client()

    collection = client.get_or_create_collection(collection_name)

    file_paths: List[Path] = [
        p for p in root_path.rglob("*.py") if ".venv" not in p.parts and "tests" not in p.parts
    ]

    if not file_paths:
        return

    documents: List[str] = []
    ids: List[str] = []
    metadatas: List[dict] = []

    for idx, path in enumerate(file_paths):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        documents.append(content)
        ids.append(f"{collection_name}:{idx}")
        metadatas.append({"path": str(path.relative_to(root_path))})

    if documents:
        collection.add(documents=documents, ids=ids, metadatas=metadatas)


def query_similar_files(
    query_text: str,
    collection_name: str,
    client: Client,
    n_results: int = 5,
) -> Iterable[dict]:
    """
    Query ChromaDB for files similar to the given text.

    Returns an iterable of metadata dictionaries.
    """
    collection = client.get_or_create_collection(collection_name)
    result = collection.query(query_texts=[query_text], n_results=n_results)
    metadatas = result.get("metadatas") or []
    if not metadatas:
        return []
    return metadatas[0]


__all__ = ["create_chroma_client", "index_repository_source_files", "query_similar_files"]

