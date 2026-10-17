# app/api/routes/project_router.py
"""The project catalog: filtered listing, facets, detail, and admin CRUD."""

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import optional_user, require_role
from app.schemas.project_schemas import (
    FacetsResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectUpdate,
)
from app.services.catalog_service import catalog_service
from app.services.project_service import project_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"], prefix="/projects")

StatusFilter = Literal["idea", "planned", "building", "done", "active"]


class ProjectFilters:
    """Shared query parameters for listing and facet counting."""

    def __init__(
        self,
        q: Optional[str] = Query(None, max_length=200, description="Words matched against title, description, technologies, domain and task"),
        domain: Optional[str] = Query(None, description="Domain code, e.g. B"),
        task: Optional[str] = Query(None, description="Task type code, e.g. det, seg, ocr"),
        level: Optional[int] = Query(None, ge=1, le=3),
        picks: bool = Query(False, description="Only recommended projects"),
        status_filter: Optional[StatusFilter] = Query(None, alias="status", description="Your status; 'active' = planned, building or done"),
        tech: Optional[str] = Query(None, max_length=120, description="Exact technology name"),
    ):
        self.q, self.domain, self.task, self.level = q, domain, task, level
        self.picks, self.status, self.tech = picks, status_filter, tech


def _caller_id(filters: ProjectFilters, user: Optional[Dict[str, Any]]) -> Optional[int]:
    if filters.status and not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to filter by your project status.")
    return user["id"] if user else None


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    filters: ProjectFilters = Depends(),
    sort: Literal["id", "title", "level", "level_desc"] = "id",
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    user: Optional[Dict[str, Any]] = Depends(optional_user),
) -> Dict[str, Any]:
    user_id = _caller_id(filters, user)
    try:
        return await project_service.list_projects(filters, user_id, sort, page, size)
    except Exception as e:
        logger.error("Error listing projects: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list projects.")


@router.get("/facets", response_model=FacetsResponse)
async def facets(
    filters: ProjectFilters = Depends(), user: Optional[Dict[str, Any]] = Depends(optional_user)
) -> Dict[str, Any]:
    """Counts per domain, task type and level. Each dimension ignores its own filter,
    so the sidebar shows how many results you would get by switching to that option."""
    user_id = _caller_id(filters, user)
    try:
        return await project_service.facets(filters, user_id)
    except Exception as e:
        logger.error("Error counting facets: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not count projects.")


async def _detail_or_404(key: str, user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    project = await project_service.get_project(key, user["id"] if user else None)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project found for '{key}'.")
    return project


@router.get("/{key}", response_model=ProjectDetailResponse)
async def get_project(key: str, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    """A project by numeric id or slug."""
    return await _detail_or_404(key, user)


# ---------------------------------------------------------------- admin

async def _resolve_refs(domain_code: Optional[str], task_code: Optional[str]):
    domain = task = None
    if domain_code is not None:
        domain = await catalog_service.get_domain_by_code(domain_code)
        if not domain:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown domain code '{domain_code}'.")
    if task_code is not None:
        task = await catalog_service.get_task_type_by_code(task_code)
        if not task:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown task type code '{task_code}'.")
    return domain, task


@router.post("", response_model=ProjectDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, admin: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    try:
        domain, task = await _resolve_refs(payload.domain_code, payload.task_type_code)
        project_id = await project_service.create_project(payload.model_dump(), domain["id"], task["id"])
        return await _detail_or_404(str(project_id), admin)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating project: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create project.")


@router.patch("/{project_id}", response_model=ProjectDetailResponse)
async def update_project(
    project_id: int, payload: ProjectUpdate, admin: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    try:
        if not await project_service.exists(project_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project found for '{project_id}'.")
        data = payload.model_dump(exclude_unset=True)
        domain, task = await _resolve_refs(data.pop("domain_code", None), data.pop("task_type_code", None))
        await project_service.update_project(
            project_id, data, domain["id"] if domain else None, task["id"] if task else None
        )
        return await _detail_or_404(str(project_id), admin)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating project %s: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update project.")


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, _: Dict[str, Any] = Depends(require_role("admin"))) -> Response:
    try:
        if not await project_service.delete_project(project_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project found for '{project_id}'.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting project %s: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete project.")
