# app/api/routes/progress_router.py
"""The signed-in user's status and notes per project, and their board."""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user
from app.schemas.progress_schemas import ProgressResponse, ProgressUpdate, StatsResponse
from app.schemas.project_schemas import ProjectResponse
from app.services.progress_service import progress_service
from app.services.project_service import project_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["progress"])


@router.put("/projects/{project_id}/progress", response_model=ProgressResponse)
async def set_progress(
    project_id: int, payload: ProgressUpdate, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        if payload.status is None and payload.notes is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Send a status, notes, or both.")
        if not await project_service.exists(project_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project with id {project_id}.")
        return await progress_service.set_progress(current_user["id"], project_id, payload.status, payload.notes)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error saving progress on project %s: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save your progress.")


@router.delete("/projects/{project_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
async def reset_progress(project_id: int, current_user: Dict[str, Any] = Depends(get_current_user)) -> Response:
    try:
        await progress_service.reset(current_user["id"], project_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error("Error resetting progress on project %s: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset your progress.")


@router.get("/me/progress", response_model=List[ProjectResponse])
async def my_projects(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    try:
        return await project_service.list_with_progress(current_user["id"])
    except Exception as e:
        logger.error("Error listing progress: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load your projects.")


@router.get("/me/stats", response_model=StatsResponse)
async def my_stats(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return await progress_service.stats(current_user["id"])
    except Exception as e:
        logger.error("Error computing stats: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load your board.")
