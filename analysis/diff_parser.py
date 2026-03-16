"""Utilities for parsing Git diffs for PRGuard AI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Iterable


@dataclass
class Hunk:
    """Represents a single diff hunk."""

    header: str
    lines: List[str]


def parse_diff(diff_text: str) -> Dict[str, List[Hunk]]:
    """
    Parse a unified diff string into a mapping of file path to hunks.

    This is intentionally minimal but suitable for small to medium diffs.
    It supports standard `git diff --unified` output.
    """
    files: Dict[str, List[Hunk]] = {}
    current_file: str | None = None
    current_hunk: Hunk | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            current_file = None
            current_hunk = None
            continue

        if line.startswith("+++ "):
            path = line[4:].strip()
            # Drop a/ or b/ prefixes if present
            if path.startswith("b/") or path.startswith("a/"):
                path = path[2:]
            current_file = path
            files.setdefault(current_file, [])
            continue

        if line.startswith("@@"):
            if current_file is None:
                continue
            if current_hunk is not None:
                files[current_file].append(current_hunk)
            current_hunk = Hunk(header=line, lines=[])
            continue

        if current_file is not None and current_hunk is not None:
            current_hunk.lines.append(line)

    if current_file is not None and current_hunk is not None:
        files[current_file].append(current_hunk)

    return files


def extract_changed_files(diff_text: str) -> List[str]:
    """
    Extract a list of file paths that were changed in the diff.
    """
    parsed = parse_diff(diff_text)
    return list(parsed.keys())


def extract_hunks(diff_text: str) -> Iterable[Hunk]:
    """
    Yield all hunks from the diff.
    """
    parsed = parse_diff(diff_text)
    for hunks in parsed.values():
        for hunk in hunks:
            yield hunk


__all__ = ["Hunk", "parse_diff", "extract_changed_files", "extract_hunks"]

