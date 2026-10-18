# app/schemas/camera_schemas.py
"""Cameras and their live status."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source_url: str = Field(min_length=3, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=200)
    pipeline: Optional[str] = Field(default=None, description="A live pipeline; null for live view only.")
    params: Dict[str, Any] = Field(default_factory=dict)
    target_fps: float = Field(default=5.0, gt=0, le=15)


class CameraUpdate(BaseModel):
    """Only the fields sent change. A running camera restarts with the new settings."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    source_url: Optional[str] = Field(default=None, min_length=3, max_length=1000)
    location: Optional[str] = Field(default=None, max_length=200)
    pipeline: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    target_fps: Optional[float] = Field(default=None, gt=0, le=15)


class SourcePreview(BaseModel):
    source_url: str = Field(min_length=3, max_length=1000)


class CameraResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    source_url: str  # without its password unless you may edit the camera
    location: Optional[str] = None
    enabled: bool
    pipeline: Optional[str] = None
    params: Dict[str, Any]
    target_fps: float
    created_at: datetime
    updated_at: datetime
    status: Dict[str, Any]


class LiveToken(BaseModel):
    token: str
    expires_in: int
    url: str  # path of the WebSocket, relative to the site root


class LivePipelines(BaseModel):
    pipelines: List[Dict[str, Any]]
    samples: List[str]
    max_live_cameras: int
    live_now: int
