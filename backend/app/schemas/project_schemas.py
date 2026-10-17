# app/schemas/project_schemas.py
"""Catalog projects: list, detail, facets and admin create/update."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.catalog_schemas import DomainResponse, TaskTypeRef
from app.schemas.progress_schemas import ProgressResponse

LEVELS = {1: "Beginner", 2: "Intermediate", 3: "Advanced"}


class ProjectResponse(BaseModel):
    id: int
    title: str
    slug: str
    description: str
    level: int
    level_name: str
    domain: DomainResponse
    task_type: TaskTypeRef
    technologies: List[str]
    is_pick: bool
    pick_reason: Optional[str]
    caution: Optional[str]
    lab: Optional[dict] = None
    progress: Optional[ProgressResponse] = None


class ProjectDetailResponse(ProjectResponse):
    steps: List[str]
    prev_id: Optional[int] = None
    next_id: Optional[int] = None


class ProjectListResponse(BaseModel):
    items: List[ProjectResponse]
    total: int
    page: int
    size: int


def _clean_techs(v: List[str]) -> List[str]:
    """Strip, drop blanks and case-insensitive duplicates, cap at 120 chars."""
    seen, out = set(), []
    for t in (x.strip() for x in v):
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t[:120])
    return out


class ProjectCreate(BaseModel):
    lab: Optional[dict] = None
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3)
    domain_code: str
    task_type_code: str
    level: int = Field(ge=1, le=3)
    technologies: List[str] = Field(default_factory=list)
    is_pick: bool = False
    pick_reason: Optional[str] = None
    caution: Optional[str] = None

    @field_validator("technologies")
    @classmethod
    def clean_techs(cls, v: List[str]) -> List[str]:
        return _clean_techs(v)


class ProjectUpdate(BaseModel):
    lab: Optional[dict] = None
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, min_length=3)
    domain_code: Optional[str] = None
    task_type_code: Optional[str] = None
    level: Optional[int] = Field(default=None, ge=1, le=3)
    technologies: Optional[List[str]] = None
    is_pick: Optional[bool] = None
    pick_reason: Optional[str] = None
    caution: Optional[str] = None

    @field_validator("technologies")
    @classmethod
    def clean_techs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return None if v is None else _clean_techs(v)


class FacetCount(BaseModel):
    key: str
    count: int


class FacetsResponse(BaseModel):
    total: int
    domains: List[FacetCount]
    task_types: List[FacetCount]
    levels: List[FacetCount]
