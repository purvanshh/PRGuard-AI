from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import WebSocket
from prguard_ai.observability.event_stream import EventBroker


@pytest.mark.anyio
async def test_event_broker_flow():
    broker = EventBroker()
    
    ws1 = MagicMock(spec=WebSocket)
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    
    ws2 = MagicMock(spec=WebSocket)
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()
    ws2.send_json.side_effect = Exception("Connection closed")
    
    # 1. Register ws1 and ws2
    await broker.register("pr#1", ws1)
    await broker.register("pr#1", ws2)
    
    ws1.accept.assert_called_once()
    ws2.accept.assert_called_once()
    
    # Check internal structure
    assert ws1 in broker._connections["pr#1"]
    assert ws2 in broker._connections["pr#1"]
    
    # 2. Broadcast event
    event = {"event": "start"}
    await broker.broadcast("pr#1", event)
    
    ws1.send_json.assert_called_once_with(event)
    ws2.send_json.assert_called_once_with(event)
    
    # ws2 failed, so it should have been discarded from the set
    assert ws1 in broker._connections["pr#1"]
    assert ws2 not in broker._connections["pr#1"]
    
    # 3. Unregister ws1
    await broker.unregister("pr#1", ws1)
    assert "pr#1" not in broker._connections
    
    # 4. Unregister nonexistent ws
    await broker.unregister("pr#1", ws1)
    
    # 5. Broadcast to no connections
    await broker.broadcast("pr#2", {"event": "none"})
