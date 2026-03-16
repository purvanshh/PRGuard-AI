"""Tests for the diff parser utilities."""

from analysis.diff_parser import parse_diff, extract_changed_files, extract_hunks


SIMPLE_DIFF = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
-old line
+new line
+another line
"""


def test_parse_diff_returns_file_mapping():
    parsed = parse_diff(SIMPLE_DIFF)
    assert "foo.py" in parsed
    hunks = parsed["foo.py"]
    assert len(hunks) == 1
    assert hunks[0].header.startswith("@@")
    assert any("new line" in l for l in hunks[0].lines)


def test_extract_changed_files_returns_file_list():
    files = extract_changed_files(SIMPLE_DIFF)
    assert files == ["foo.py"]


def test_extract_hunks_yields_hunks():
    hunks = list(extract_hunks(SIMPLE_DIFF))
    assert len(hunks) == 1
    assert hunks[0].header.startswith("@@")

