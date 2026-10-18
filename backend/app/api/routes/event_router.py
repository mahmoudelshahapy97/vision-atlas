# app/api/routes/event_router.py
"""Camera events of the active workspace (X-Workspace-Id): list, stats,
handle; and the alerts WebSocket that pushes new ones as they happen."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.api.deps import require_workspace, workspace_access
from app.core.config import config
from app.core.security import create_media_token, decode_media_token
from app.schemas.event_schemas import AlertsToken, EventPage, EventResponse, EventStats, EventUpdate, EventStatus, Severity
from app.services.alert_hub import alert_hub
from app.services.camera_service import camera_service
from app.services.event_service import event_service
from app.services.stream_manager import stream_manager
from app.services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"], prefix="/events")
ws_router = APIRouter(tags=["events"], prefix="/ws")

ALERTS_SCOPE = "alerts"


@router.get("", response_model=EventPage)
async def list_events(
    camera_id: Optional[int] = None,
    kind: Optional[str] = Query(default=None, max_length=60),
    status_: Optional[EventStatus] = Query(default=None, alias="status"),
    severity: Optional[Severity] = None,
    since: Optional[datetime] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    access: Dict[str, Any] = Depends(require_workspace("viewer")),
) -> Dict[str, Any]:
    items, total = await event_service.list(
        access["workspace"]["id"], camera_id, kind, status_, severity, since, page, per_page
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/stats", response_model=EventStats)
async def event_stats(access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    """The dashboard's numbers."""
    wid = access["workspace"]["id"]
    cameras = await camera_service.list(wid)
    return {
        **await event_service.stats(wid),
        "cameras": len(cameras),
        "cameras_live": sum(1 for c in cameras if stream_manager.status_of(c["id"])["running"]),
        "kinds": await event_service.kinds(wid),
    }


@router.post("/alerts-token", response_model=AlertsToken)
async def alerts_token(access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    wid = access["workspace"]["id"]
    return {
        "token": create_media_token(access["user"]["id"], ALERTS_SCOPE, wid, config.live_token_minutes),
        "expires_in": config.live_token_minutes * 60,
        "url": f"{config.app_api_prefix}/ws/alerts/{wid}",
    }


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: int, access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    ev = await event_service.get(event_id, access["workspace"]["id"])
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return ev


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: int, payload: EventUpdate, access: Dict[str, Any] = Depends(require_workspace("operator"))
) -> Dict[str, Any]:
    ev = await event_service.set_status(event_id, access["workspace"]["id"], payload.status, access["user"]["id"])
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    alert_hub.publish(access["workspace"]["id"], {"type": "status", "id": ev["id"], "status": ev["status"]})
    return ev


async def _can_follow(user_id: int, workspace_id: int) -> bool:
    user = await user_service.get_by_id(user_id)
    if not user or not user["is_active"]:
        return False
    try:
        await workspace_access(workspace_id, user, "viewer")
        return True
    except HTTPException:
        return False


@ws_router.websocket("/alerts/{workspace_id}")
async def alerts(websocket: WebSocket, workspace_id: int, token: str = Query(default="")) -> None:
    """New events of the workspace as {"type": "event", "event": {...}} and
    status changes as {"type": "status", id, status}; {"type": "ping"} every
    30 s keeps proxies from closing an idle connection."""
    payload = decode_media_token(token, ALERTS_SCOPE, workspace_id)
    user_id = int(payload["sub"]) if payload else None
    if user_id is None or not await _can_follow(user_id, workspace_id):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    queue = alert_hub.subscribe(workspace_id)
    checked = time.monotonic()
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                message = {"type": "ping"}
            if time.monotonic() - checked > 60:
                if not await _can_follow(user_id, workspace_id):
                    await websocket.close(code=4403)
                    return
                checked = time.monotonic()
            await websocket.send_json(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        alert_hub.unsubscribe(workspace_id, queue)
