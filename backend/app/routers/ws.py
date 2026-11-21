"""WebSocket router for real-time crawler logs and high-risk alerts (/ws/alerts)."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import utc_now_iso
from app.models import WebSocketAlertEvent

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket) -> None:
    ws_manager = websocket.app.state.ws_manager
    await ws_manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                pong = WebSocketAlertEvent(
                    type="pong",
                    timestamp=utc_now_iso(),
                    message="pong",
                )
                await websocket.send_json(pong.model_dump())
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)
