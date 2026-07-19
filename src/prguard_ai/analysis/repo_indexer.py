"""Repository indexing utilities for PRGuard AI using ChromaDB."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from prguard_ai.config.settings import settings


DEFAULT_COLLECTION = "prguard_repo_index"

_COLLECTION_CACHE: Dict[str, Any] = {}

_FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?(?:def|class|fn|func|function)\s+(\w+)",
    re.MULTILINE,
)


def _chunks_from_repo(repo_path: Path, max_chars: int = 1500) -> List[dict]:
    chunks: List[dict] = []
    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix not in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".swift"}:
            continue
        if any(part.startswith(".") or part == "node_modules" or part == "__pycache__" for part in file_path.parts):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not text.strip():
            continue

        rel_path = str(file_path.relative_to(repo_path))
        for match in _FUNCTION_PATTERN.finditer(text):
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 600)
            snippet = text[start:end].strip()
            if len(snippet) > max_chars:
                snippet = snippet[:max_chars]
            chunks.append({
                "id": hashlib.md5(f"{rel_path}:{match.start()}".encode()).hexdigest()[:16],
                "path": rel_path,
                "code": snippet,
                "name": match.group(1),
            })
        if not chunks or chunks[-1]["path"] != rel_path:
            first_line = text.splitlines()[0] if text.splitlines() else ""
            chunks.append({
                "id": hashlib.md5(f"{rel_path}:top".encode()).hexdigest()[:16],
                "path": rel_path,
                "code": text[:max_chars],
                "name": rel_path,
            })
    return chunks


def _get_client() -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    persist_dir = settings.chroma_persist_dir
    return chromadb.Client(
        ChromaSettings(
            persist_directory=persist_dir,
            anonymized_telemetry=False,
        )
    )


def _get_or_create_collection(collection_name: str) -> Any:
    if collection_name in _COLLECTION_CACHE:
        return _COLLECTION_CACHE[collection_name]
    client = _get_client()
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        collection = client.create_collection(collection_name)
    _COLLECTION_CACHE[collection_name] = collection
    return collection


def index_repository(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    path = Path(repo_path)
    if not path.exists():
        return
    collection = _get_or_create_collection(collection_name)
    chunks = _chunks_from_repo(path)
    if not chunks:
        return

    existing_ids = set()
    try:
        existing = collection.get(limit=10000)
        existing_ids = set(existing["ids"])
    except Exception:
        pass

    new_chunks = [c for c in chunks if c["id"] not in existing_ids]
    if not new_chunks:
        return

    collection.add(
        ids=[c["id"] for c in new_chunks],
        documents=[c["code"] for c in new_chunks],
        metadatas=[{"path": c["path"], "name": c["name"]} for c in new_chunks],
    )


def initialize_repo_index(repo_path: str | Path, collection_name: str = DEFAULT_COLLECTION) -> None:
    index_repository(repo_path, collection_name)


def retrieve_similar_code(
    snippet: str,
    collection_name: str = DEFAULT_COLLECTION,
    n_results: int = 5,
) -> Iterable[Tuple[str, str]]:
    if not snippet.strip():
        return []
    try:
        collection = _get_or_create_collection(collection_name)
        results = collection.query(query_texts=[snippet], n_results=n_results)
        if not results or not results.get("metadatas"):
            return []
        out: List[Tuple[str, str]] = []
        for metas, docs in zip(results["metadatas"][0], results["documents"][0]):
            path = metas.get("path", "unknown") if metas else "unknown"
            doc = docs or ""
            out.append((path, doc[:400]))
        return out
    except Exception:
        return []


__all__ = ["index_repository", "initialize_repo_index", "retrieve_similar_code", "DEFAULT_COLLECTION"]
