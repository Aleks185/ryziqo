"""Disconnect-safe WebSocket manager for /ws/alerts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from app.database import utc_now_iso
from app.models import WebSocketAlertEvent

logger = logging.getLogger("investwatch.ws")


class AlertWebSocketManager:
    """Manages active /ws/alerts clients and broadcasts events without breaking crawlers."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        welcome = WebSocketAlertEvent(
            type="connected",
            timestamp=utc_now_iso(),
            message="Połączono z kanałem alertów #InvestWatch (/ws/alerts).",
        )
        await self._send_safe(websocket, welcome.model_dump())

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event: WebSocketAlertEvent) -> None:
        payload = event.model_dump()
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            return

        stale: list[WebSocket] = []
        for ws in targets:
            ok = await self._send_safe(ws, payload)
            if not ok:
                stale.append(ws)

        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.discard(ws)

    async def _send_safe(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except Exception as exc:
            logger.debug("WebSocket client disconnected during send: %s", exc)
            return False

    @property
    def active_connections_count(self) -> int:
        return len(self._connections)
