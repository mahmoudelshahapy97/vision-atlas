# app/schemas/lab_schemas.py
"""Vision Lab runs and uploaded models."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

# Mirrors the CHECK constraint on inference_run.status
RUN_STATUSES = ("queued", "running", "done", "error")


class RunResponse(BaseModel):
    public_id: str
    project_id: Optional[int]
    pipeline: str
    status: str
    progress: float
    params: dict
    inputs: list
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RunSummary(BaseModel):
    public_id: str
    project_id: Optional[int]
    pipeline: str
    status: str
    progress: float
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    summary: list = []
    thumbnail: Optional[str] = None
    project_title: Optional[str] = None


class CustomModelResponse(BaseModel):
    id: int
    name: str
    task: str
    classes: Optional[List] = None
    size_bytes: int
    is_public: bool
    project_id: Optional[int]
    owner_id: Optional[int]
    created_at: Optional[datetime] = None
