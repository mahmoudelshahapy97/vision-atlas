# app/api/routes/analytics_router.py
"""Analytics of the active workspace (X-Workspace-Id): events over time, by
camera and kind, a weekday x hour heatmap, the cameras' measured metrics,
and a CSV export. `tz` is the viewer's IANA timezone (Intl in the browser)."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import require_workspace
from app.services.analytics_service import analytics_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analytics"], prefix="/analytics")

WINDOWS = (1, 7, 30, 90)


def _days(days: int = Query(default=7, description="1, 7, 30 or 90")) -> int:
    if days not in WINDOWS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="days must be 1, 7, 30 or 90.")
    return days


def _bad_tz(e: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/summary")
async def summary(
    days: int = Depends(_days),
    camera_id: Optional[int] = None,
    tz: str = Query(default="UTC", max_length=64),
    access: Dict[str, Any] = Depends(require_workspace("viewer")),
) -> Dict[str, Any]:
    try:
        return await analytics_service.summary(access["workspace"]["id"], days, camera_id, tz)
    except ValueError as e:
        raise _bad_tz(e)


@router.get("/metrics")
async def metrics(
    days: int = Depends(_days),
    camera_id: Optional[int] = None,
    name: Optional[str] = Query(default=None, max_length=80),
    tz: str = Query(default="UTC", max_length=64),
    access: Dict[str, Any] = Depends(require_workspace("viewer")),
) -> Dict[str, Any]:
    """One measured metric (the first available when `name` is not given),
    per camera, with the list of metrics there are in the window."""
    try:
        return await analytics_service.metrics(access["workspace"]["id"], days, camera_id, name, tz)
    except ValueError as e:
        raise _bad_tz(e)


@router.get("/events.csv", response_class=Response)
async def events_csv(
    days: int = Depends(_days),
    camera_id: Optional[int] = None,
    tz: str = Query(default="UTC", max_length=64),
    access: Dict[str, Any] = Depends(require_workspace("viewer")),
) -> Response:
    try:
        body = await analytics_service.events_csv(access["workspace"]["id"], days, camera_id, tz)
    except ValueError as e:
        raise _bad_tz(e)
    name = f"events-{access['workspace']['slug']}-{days}d.csv"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
