# app/schemas/event_schemas.py
"""Camera events."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

EventStatus = Literal["open", "acknowledged", "resolved", "false_positive"]
Severity = Literal["info", "warning", "critical"]


class EventResponse(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    pipeline: str
    kind: str
    label: str
    severity: Severity
    track_id: Optional[int] = None
    confidence: Optional[float] = None
    data: Dict[str, Any]
    snapshot_url: Optional[str] = None
    status: EventStatus
    handled_by_name: Optional[str] = None
    handled_at: Optional[datetime] = None
    occurred_at: datetime


class EventPage(BaseModel):
    items: List[EventResponse]
    total: int
    page: int
    per_page: int


class EventUpdate(BaseModel):
    status: EventStatus


class EventStats(BaseModel):
    total: int
    open: int
    open_critical: int
    last_24h: int
    last_event_at: Optional[datetime] = None
    cameras: int
    cameras_live: int
    kinds: List[str]


class AlertsToken(BaseModel):
    token: str
    expires_in: int
    url: str
