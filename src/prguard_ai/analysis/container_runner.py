"""Containerized repository analysis for PRGuard AI.

This module is responsible for running the PR analysis pipeline inside a
short‑lived, isolated container. It does NOT change any agent logic – it is an
orchestration layer around the existing code.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping


DEFAULT_IMAGE = os.getenv("PRGUARD_ANALYSIS_IMAGE", "prguard-ai-analysis:latest")
CONTAINER_REPO_MOUNT = Path("/workspace/repo")
MAX_RUNTIME_SECONDS = 5 * 60  # 5 minutes


class ContainerRunError(RuntimeError):
    pass


def _build_docker_command(
    repo_path: Path,
    pr_id: str,
    extra_env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build a docker run command enforcing security and resource limits."""
    env = {
        "PR_ID": pr_id,
        "REPO_PATH": str(CONTAINER_REPO_MOUNT),
    }
    if extra_env:
        env.update(extra_env)

    cmd: list[str] = [
        "docker",
        "run",
        "--rm",
        "--cpus",
        "2",
        "--memory",
        "1g",
        "--memory-swap",
        "1g",
        "--pids-limit",
        "256",
        "--user",
        "1000:1000",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--network",
        "none",
        "-v",
        f"{repo_path.resolve()}:{CONTAINER_REPO_MOUNT}:ro",
    ]

    for k, v in env.items():
        cmd.extend(["-e", f"{k}={v}"])

    cmd.append(DEFAULT_IMAGE)
    return cmd


def run_analysis_in_container(
    repo_path: Path,
    pr_id: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the full PR analysis pipeline inside an ephemeral container.

    The container image is expected to execute the analysis and print a single
    line of JSON to stdout representing the arbitrator result.
    """
    if not repo_path.exists():
        raise ContainerRunError(f"Repository path does not exist: {repo_path}")

    cmd = _build_docker_command(repo_path=repo_path, pr_id=pr_id, extra_env=env or {})

    try:
        completed = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=MAX_RUNTIME_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ContainerRunError("Container analysis timed out.") from exc

    if completed.returncode != 0:
        raise ContainerRunError(
            f"Container analysis failed (exit {completed.returncode}): {completed.stderr.strip()}"
        )

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise ContainerRunError("Container analysis produced no output.")

    try:
        result = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise ContainerRunError("Failed to parse container analysis output as JSON.") from exc

    if not isinstance(result, dict):
        raise ContainerRunError("Container analysis output must be a JSON object.")

    return result


__all__ = ["run_analysis_in_container", "ContainerRunError", "DEFAULT_IMAGE", "CONTAINER_REPO_MOUNT"]

