"""Utilities for parsing Git diffs for PRGuard AI.

This module parses unified Git diffs into structured hunks with precise
line-number tracking for additions and removals. It is intentionally
lightweight but robust enough for typical pull request diffs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class DiffLine:
    """Represents a single line in a diff hunk."""

    content: str
    line_type: str  # one of: "add", "remove", "context"
    old_lineno: int | None
    new_lineno: int | None


@dataclass
class DiffHunk:
    """Represents a single unified diff hunk for a file."""

    file_path: str
    header: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[DiffLine] = field(default_factory=list)


def _parse_hunk_header(header: str) -> Tuple[int, int, int, int]:
    """
    Parse a unified diff hunk header.

    Example: @@ -1,3 +1,4 @@
    """
    # Strip leading/trailing markers.
    header = header.strip()
    if not header.startswith("@@"):
        raise ValueError(f"Invalid hunk header: {header!r}")

    # Remove @@ prefix/suffix and split the range parts.
    without_markers = header.strip("@").strip()
    # Now we expect something like: "-1,3 +1,4" or "-1 +1"
    parts = without_markers.split(" ")
    old_part = next(p for p in parts if p.startswith("-"))
    new_part = next(p for p in parts if p.startswith("+"))

    def _parse_range(part: str) -> Tuple[int, int]:
        # part like "-1,3" or "+10" (implicit length 1)
        part = part[1:]  # drop leading +/-.
        if "," in part:
            start_s, length_s = part.split(",", 1)
            return int(start_s), int(length_s)
        return int(part), 1

    old_start, old_len = _parse_range(old_part)
    new_start, new_len = _parse_range(new_part)
    return old_start, old_len, new_start, new_len


def parse_diff(diff_text: str) -> Dict[str, List[DiffHunk]]:
    """
    Parse a unified diff string into a mapping of file path to diff hunks.

    Supports standard ``git diff --unified`` output and tracks exact line
    numbers for each hunk line.
    """
    files: Dict[str, List[DiffHunk]] = {}
    current_file: str | None = None
    current_hunk: DiffHunk | None = None
    old_lineno: int | None = None
    new_lineno: int | None = None

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\n")

        if line.startswith("diff --git"):
            current_file = None
            current_hunk = None
            old_lineno = None
            new_lineno = None
            continue

        if line.startswith("+++ "):
            path = line[4:].strip()
            # Drop a/ or b/ prefixes if present.
            if path.startswith("b/") or path.startswith("a/"):
                path = path[2:]
            current_file = path
            files.setdefault(current_file, [])
            continue

        if line.startswith("@@"):
            if current_file is None:
                continue
            # Finalize previous hunk.
            if current_hunk is not None:
                files[current_file].append(current_hunk)

            old_start, old_len, new_start, new_len = _parse_hunk_header(line)
            current_hunk = DiffHunk(
                file_path=current_file,
                header=line,
                old_start=old_start,
                old_lines=old_len,
                new_start=new_start,
                new_lines=new_len,
                lines=[],
            )
            old_lineno = old_start
            new_lineno = new_start
            continue

        if current_file is None or current_hunk is None:
            continue

        if not line:
            # Empty context line
            current_hunk.lines.append(
                DiffLine(content="", line_type="context", old_lineno=old_lineno, new_lineno=new_lineno)
            )
            if old_lineno is not None:
                old_lineno += 1
            if new_lineno is not None:
                new_lineno += 1
            continue

        prefix = line[0]
        content = line[1:] if prefix in {"+", "-"} else line

        if prefix == "+":
            current_hunk.lines.append(
                DiffLine(content=content, line_type="add", old_lineno=None, new_lineno=new_lineno)
            )
            if new_lineno is not None:
                new_lineno += 1
        elif prefix == "-":
            current_hunk.lines.append(
                DiffLine(content=content, line_type="remove", old_lineno=old_lineno, new_lineno=None)
            )
            if old_lineno is not None:
                old_lineno += 1
        else:
            current_hunk.lines.append(
                DiffLine(content=line, line_type="context", old_lineno=old_lineno, new_lineno=new_lineno)
            )
            if old_lineno is not None:
                old_lineno += 1
            if new_lineno is not None:
                new_lineno += 1

    if current_file is not None and current_hunk is not None:
        files[current_file].append(current_hunk)

    return files


def extract_changed_files(diff: str | Dict[str, List[DiffHunk]]) -> List[str]:
    """
    Extract a list of file paths that were changed in the diff.

    Accepts either a raw diff string or the parsed diff mapping.
    """
    if isinstance(diff, str):
        parsed = parse_diff(diff)
    else:
        parsed = diff
    return list(parsed.keys())


def extract_hunks(file_diff: str | List[DiffHunk] | Dict[str, List[DiffHunk]]) -> Iterable[DiffHunk]:
    """
    Yield all hunks from the diff.

    Accepts:
    - raw diff string
    - parsed mapping of file -> hunks
    - list of hunks for a single file
    """
    if isinstance(file_diff, str):
        mapping = parse_diff(file_diff)
        for hunks in mapping.values():
            for h in hunks:
                yield h
    elif isinstance(file_diff, dict):
        for hunks in file_diff.values():
            for h in hunks:
                yield h
    else:
        for h in file_diff:
            yield h


def extract_context_lines(file_path: str | Path, start_line: int, window: int = 20) -> List[str]:
    """
    Extract surrounding context lines from a file on disk.

    Args:
        file_path: Path to the source file.
        start_line: 1-based line number around which to capture context.
        window: Number of lines before and after the start_line to include.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    try:
        all_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    idx = max(start_line - 1, 0)
    begin = max(idx - window, 0)
    end = min(idx + window + 1, len(all_lines))
    return all_lines[begin:end]


__all__ = [
    "DiffLine",
    "DiffHunk",
    "parse_diff",
    "extract_changed_files",
    "extract_hunks",
    "extract_context_lines",
]

