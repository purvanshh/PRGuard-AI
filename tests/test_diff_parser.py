"""Tests for the diff parser utilities."""

from analysis.diff_parser import (
    DiffHunk,
    DiffLine,
    extract_changed_files,
    extract_context_lines,
    extract_hunks,
    parse_diff,
)


SIMPLE_DIFF = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
-old line
+new line
+another line
"""


def test_parse_diff_returns_file_mapping_with_line_numbers(tmp_path):
    parsed = parse_diff(SIMPLE_DIFF)
    assert "foo.py" in parsed
    hunks = parsed["foo.py"]
    assert len(hunks) == 1
    hunk = hunks[0]
    assert isinstance(hunk, DiffHunk)
    assert hunk.header.startswith("@@")
    added = [l for l in hunk.lines if l.line_type == "add"]
    assert len(added) == 2
    # New line numbers should be populated for added lines.
    assert all(a.new_lineno is not None for a in added)


def test_extract_changed_files_accepts_parsed_mapping():
    parsed = parse_diff(SIMPLE_DIFF)
    files = extract_changed_files(parsed)
    assert files == ["foo.py"]


def test_extract_hunks_accepts_string_and_mapping():
    hunks_from_str = list(extract_hunks(SIMPLE_DIFF))
    assert len(hunks_from_str) == 1
    parsed = parse_diff(SIMPLE_DIFF)
    hunks_from_mapping = list(extract_hunks(parsed))
    assert len(hunks_from_mapping) == 1
    assert hunks_from_str[0].header == hunks_from_mapping[0].header


def test_extract_context_lines_reads_file(tmp_path):
    file_path = tmp_path / "foo.py"
    file_path.write_text("a\nb\nc\nd\n", encoding="utf-8")
    ctx = extract_context_lines(str(file_path), start_line=2, window=1)
    assert "a" in ctx and "c" in ctx


