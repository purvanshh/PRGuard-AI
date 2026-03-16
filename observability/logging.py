"""Execution logging utilities for PRGuard AI."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List


DB_PATH = Path("prguard_logs.sqlite")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            confidence REAL,
            token_usage INTEGER,
            payload TEXT NOT NULL
        )
        """
    )
    return conn


def log_agent_execution(
    pr_id: str,
    agent: str,
    started_at: float,
    finished_at: float,
    output: Dict[str, Any],
    token_usage: int | None = None,
) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO agent_logs (pr_id, agent, started_at, finished_at, confidence, token_usage, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(pr_id),
                agent,
                started_at,
                finished_at,
                float(output.get("confidence", 0.0)),
                int(token_usage or 0),
                json.dumps(output),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_pr_logs(pr_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT agent, started_at, finished_at, confidence, token_usage, payload "
            "FROM agent_logs WHERE pr_id = ? ORDER BY started_at",
            (str(pr_id),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    logs: List[Dict[str, Any]] = []
    for agent, started_at, finished_at, confidence, token_usage, payload in rows:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {}
        logs.append(
            {
                "agent": agent,
                "started_at": started_at,
                "finished_at": finished_at,
                "confidence": confidence,
                "token_usage": token_usage,
                "output": parsed,
            }
        )
    return logs


__all__ = ["log_agent_execution", "fetch_pr_logs", "DB_PATH"]

