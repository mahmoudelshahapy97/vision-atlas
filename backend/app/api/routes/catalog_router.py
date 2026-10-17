# app/api/routes/catalog_router.py
"""Reference data for the catalog filters: domains, task types, technologies."""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.catalog_schemas import DomainWithCount, TaskTypeResponse, TechnologyResponse
from app.services.catalog_service import catalog_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])


@router.get("/domains", response_model=List[DomainWithCount])
async def list_domains() -> List[Dict[str, Any]]:
    try:
        return await catalog_service.list_domains()
    except Exception as e:
        logger.error("Error listing domains: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list domains.")


@router.get("/task-types", response_model=List[TaskTypeResponse])
async def list_task_types() -> List[Dict[str, Any]]:
    try:
        return await catalog_service.list_task_types()
    except Exception as e:
        logger.error("Error listing task types: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list task types.")


@router.get("/technologies", response_model=List[TechnologyResponse])
async def list_technologies(limit: int = Query(50, ge=1, le=500)) -> List[Dict[str, Any]]:
    try:
        return await catalog_service.list_technologies(limit)
    except Exception as e:
        logger.error("Error listing technologies: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list technologies.")
