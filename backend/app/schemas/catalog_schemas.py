# app/schemas/catalog_schemas.py
"""Domains, task types and technologies: the catalog's reference data."""

from typing import List

from pydantic import BaseModel


class DomainResponse(BaseModel):
    id: int
    code: str
    name: str
    slug: str


class DomainWithCount(DomainResponse):
    project_count: int


class TaskTypeRef(BaseModel):
    id: int
    code: str
    name: str
    metric: str


class TaskTypeResponse(TaskTypeRef):
    steps: List[str]
    project_count: int


class TechnologyResponse(BaseModel):
    name: str
    project_count: int
