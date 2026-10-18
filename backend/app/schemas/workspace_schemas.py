# app/schemas/workspace_schemas.py
"""Workspaces and their members."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

WorkspaceRole = Literal["viewer", "operator", "admin"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    # None: every live pipeline. A list restricts the cameras to those.
    enabled_pipelines: Optional[List[str]] = None
    max_cameras: int = Field(default=16, ge=0, le=1000)


class WorkspaceUpdate(BaseModel):
    """Only the fields sent are changed; send enabled_pipelines: null to allow every pipeline."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    enabled_pipelines: Optional[List[str]] = None
    max_cameras: Optional[int] = Field(default=None, ge=0, le=1000)
    is_active: Optional[bool] = None


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    enabled_pipelines: Optional[List[str]] = None
    max_cameras: int
    is_active: bool
    member_count: int = 0
    my_role: Optional[WorkspaceRole] = None
    created_at: datetime
    updated_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: WorkspaceRole = "viewer"


class MemberUpdate(BaseModel):
    role: WorkspaceRole


class MemberResponse(BaseModel):
    user_id: int
    email: str
    name: str
    is_active: bool
    role: WorkspaceRole
    created_at: datetime
