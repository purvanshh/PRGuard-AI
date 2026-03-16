"""Lightweight event streaming utilities for live agent execution views."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Set

from fastapi import WebSocket


class EventBroker:
    """Per-PR event broker for WebSocket clients."""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, pr_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(pr_id, set()).add(websocket)

    async def unregister(self, pr_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(pr_id)
            if conns and websocket in conns:
                conns.remove(websocket)
            if conns and not conns:
                self._connections.pop(pr_id, None)

    async def broadcast(self, pr_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._connections.get(pr_id, set()))
        if not conns:
            return
        dead: List[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                conns = self._connections.get(pr_id, set())
                for ws in dead:
                    conns.discard(ws)


broker = EventBroker()


__all__ = ["broker"]

