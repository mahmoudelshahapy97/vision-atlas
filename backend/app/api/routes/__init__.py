# app/api/routes/__init__.py
from fastapi import APIRouter

from app.api.routes import (
    analytics_router,
    auth_router,
    camera_router,
    catalog_router,
    event_router,
    lab_router,
    model_router,
    progress_router,
    project_router,
    run_router,
    user_router,
    workspace_router,
)
from app.core.config import config

# Everything hangs off the API prefix ("/api").
router = APIRouter(prefix=config.app_api_prefix)

router.include_router(auth_router.router)
router.include_router(user_router.router)
router.include_router(workspace_router.router)
router.include_router(catalog_router.router)
router.include_router(lab_router.router)  # before project_router: /projects/{id}/lab vs /projects/{key}
router.include_router(project_router.router)
router.include_router(progress_router.router)
router.include_router(run_router.router)
router.include_router(model_router.router)
router.include_router(camera_router.router)
router.include_router(camera_router.ws_router)
router.include_router(event_router.router)
router.include_router(event_router.ws_router)
router.include_router(analytics_router.router)
