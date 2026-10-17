# app/schemas/progress_schemas.py
"""A user's status and notes on a project, and their board statistics."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Mirrors the CHECK constraint on user_project.status
Status = Literal["idea", "planned", "building", "done"]
STATUSES = ("idea", "planned", "building", "done")


class ProgressUpdate(BaseModel):
    status: Optional[Status] = None
    notes: Optional[str] = Field(default=None, max_length=20000)


class ProgressResponse(BaseModel):
    project_id: int
    status: Status
    notes: str
    updated_at: Optional[datetime] = None


class DomainProgress(BaseModel):
    code: str
    name: str
    total: int
    started: int
    done: int


class StatsResponse(BaseModel):
    total: int
    counts: Dict[str, int]
    by_domain: List[DomainProgress]
    recent: List[ProgressResponse]
