"""Execution of the Semgrep binary against a repository sandbox."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from prguard_ai.semgrep.parser import SemgrepFinding, parse_semgrep_json

logger = logging.getLogger(__name__)


class SemgrepScanner:
    """Runs Semgrep scans and returns normalized findings.

    The scanner degrades gracefully: a missing binary, scan failure, or
    timeout returns an empty finding set instead of raising, so the PR review
    pipeline never fails because Semgrep is unavailable.
    """

    def __init__(
        self,
        binary: str | None = None,
        configs: List[str] | None = None,
        timeout_seconds: int = 90,
        max_target_bytes: int = 2_000_000,
    ) -> None:
        self.binary = binary or "semgrep"
        self.configs = configs or ["p/default"]
        self.timeout_seconds = int(timeout_seconds)
        self.max_target_bytes = int(max_target_bytes)

    def _binary_available(self) -> bool:
        return shutil.which(self.binary) is not None

    @staticmethod
    def _ref_resolves(target: Path, ref: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _build_command(self, target: Path, baseline_ref: str | None) -> List[str]:
        command = [
            self.binary,
            "scan",
            "--json",
            "--metrics=off",
            "--max-target-bytes",
            str(self.max_target_bytes),
        ]
        for config in self.configs:
            command.append(f"--config={config}")
        if baseline_ref:
            ref = baseline_ref.strip()
            if ref and self._ref_resolves(target, ref):
                command.append(f"--baseline-ref={ref}")
            elif ref:
                logger.warning("Semgrep baseline ref %s not found in %s; scanning full tree", ref, target)
        command.append(str(target))
        return command

    def scan(self, target: Path, baseline_ref: str | None = None) -> List[SemgrepFinding]:
        """Scan the given directory and return normalized findings."""
        if not self._binary_available():
            logger.warning("Semgrep binary '%s' not found; skipping scan of %s", self.binary, target)
            return []

        target = Path(target)
        if not target.is_dir():
            logger.warning("Semgrep target %s is not a directory; skipping scan", target)
            return []

        command = self._build_command(target, baseline_ref)
        logger.info("Running semgrep scan: %s", " ".join(command))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.error("Semgrep scan timed out after %ss on %s", self.timeout_seconds, target)
            return []
        except Exception as exc:
            logger.error("Semgrep scan failed on %s: %s", target, exc)
            return []

        if completed.returncode not in (0, 1):
            logger.error(
                "Semgrep exited with code %s on %s: %s",
                completed.returncode,
                target,
                completed.stderr[:500],
            )
            return []

        try:
            return parse_semgrep_json(completed.stdout)
        except Exception as exc:
            logger.error("Failed to parse semgrep output from %s: %s", target, exc)
            return []


__all__ = ["SemgrepScanner"]
