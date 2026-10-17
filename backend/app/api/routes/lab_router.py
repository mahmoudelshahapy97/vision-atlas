# app/api/routes/lab_router.py
"""Vision Lab catalog: pipelines, support levels, and a project's lab page."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import optional_user
from app.services.lab_service import SUPPORT_LEVELS, lab_service
from app.services.project_service import project_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vision lab"])


@router.get("/lab/pipelines")
async def list_pipelines() -> List[Dict[str, Any]]:
    return lab_service.list_pipelines()


@router.get("/lab/support-levels")
async def support_levels() -> List[Dict[str, Any]]:
    return SUPPORT_LEVELS


@router.get("/projects/{project_id}/lab")
async def project_lab(project_id: int, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    try:
        project = await project_service.get_lab_context(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project with id {project_id}.")
        if not lab_service.has_lab(project):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This project doesn't have a lab yet.")
        return await lab_service.project_lab(project, user["id"] if user else None)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error loading lab for project %s: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load this lab.")
