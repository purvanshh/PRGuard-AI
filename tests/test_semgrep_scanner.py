"""Tests for the Semgrep scanner wrapper (Phase 4)."""

import json
import subprocess
from pathlib import Path

from prguard_ai.semgrep.scanner import SemgrepScanner

FINDING = {
    "check_id": "rules.python.no-unsafe-eval",
    "path": "main.py",
    "start": {"line": 3, "col": 1},
    "extra": {"message": "Detected eval()", "severity": "ERROR", "lines": "eval(x)"},
}


def test_binary_missing_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    scanner = SemgrepScanner()
    assert scanner.scan(tmp_path) == []


def test_target_not_dir_returns_empty(monkeypatch, tmp_path):
    file_target = tmp_path / "file.py"
    file_target.write_text("x = 1")
    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    scanner = SemgrepScanner()
    assert scanner.scan(file_target) == []


def test_timeout_returns_empty(monkeypatch, tmp_path):
    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["semgrep"], timeout=5)

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    scanner = SemgrepScanner(timeout_seconds=5)
    assert scanner.scan(tmp_path) == []


def test_nonzero_fatal_returncode_returns_empty(monkeypatch, tmp_path):
    class _Completed:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Completed())
    scanner = SemgrepScanner()
    assert scanner.scan(tmp_path) == []


def test_success_parses_results(monkeypatch, tmp_path):
    class _Completed:
        returncode = 0
        stdout = json.dumps({"results": [FINDING]})
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Completed())
    scanner = SemgrepScanner(configs=["p/owasp-top-ten"])
    findings = scanner.scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].rule_id == "rules.python.no-unsafe-eval"
    assert findings[0].severity == "high"


def test_baseline_ref_added_when_ref_resolves(monkeypatch, tmp_path):
    captured = {}

    class _Completed:
        returncode = 0
        stdout = json.dumps({"results": []})
        stderr = ""

    def _fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _Completed()  # returncode 0 => ref resolves
        captured["cmd"] = cmd
        return _Completed()

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    scanner = SemgrepScanner(configs=["p/default"])
    scanner.scan(tmp_path, baseline_ref="origin/main")
    assert "--baseline-ref=origin/main" in captured["cmd"]


def test_baseline_ref_skipped_when_ref_missing(monkeypatch, tmp_path):
    captured = {}

    class _NoRef:
        returncode = 128
        stdout = ""
        stderr = "unknown ref"

    class _Ok:
        returncode = 0
        stdout = json.dumps({"results": []})
        stderr = ""

    def _fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _NoRef()
        captured["cmd"] = cmd
        return _Ok()

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    scanner = SemgrepScanner(configs=["p/default"])
    scanner.scan(tmp_path, baseline_ref="origin/main")
    assert not any("--baseline-ref" in part for part in captured["cmd"])


def test_command_contains_configs_and_bounds(monkeypatch, tmp_path):
    captured = {}

    class _Ok:
        returncode = 0
        stdout = json.dumps({"results": []})
        stderr = ""

    def _fake_run(cmd, **kwargs):
        if "rev-parse" not in cmd:
            captured["cmd"] = cmd
        return _Ok()

    monkeypatch.setattr("shutil.which", lambda _bin: "/usr/bin/semgrep")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    scanner = SemgrepScanner(configs=["p/a", "p/b"], max_target_bytes=123456)
    scanner.scan(tmp_path)
    joined = " ".join(captured["cmd"])
    assert "--config=p/a" in joined
    assert "--config=p/b" in joined
    assert "--max-target-bytes" in joined
    assert str(tmp_path) in joined
