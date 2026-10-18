# app/api/routes/user_router.py
"""Account management. Every route here requires the admin role.

The guards keep at least one active admin: an admin can't delete or demote
themself, and the last active admin can't be demoted, deactivated or deleted.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import require_role
from app.core.database import db_manager
from app.schemas.auth_schemas import UserRow
from app.schemas.user_schemas import PasswordReset, SystemRole, UserCreate, UserPage, UserUpdate
from app.services.auth_service import auth_service
from app.services.media_service import media_service
from app.services.user_service import user_service
from app.vision import runner
from app.vision.registry import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["users"], prefix="/users", dependencies=[Depends(require_role("admin"))])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


@router.get("", response_model=UserPage)
async def list_users(
    q: Optional[str] = Query(default=None, max_length=120),
    role: Optional[SystemRole] = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    try:
        items, total = await user_service.list_users(q, role, page, per_page)
        return {"items": items, "total": total, "page": page, "per_page": per_page}
    except Exception as e:
        logger.error("Error listing users: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list users.")


@router.post("", response_model=UserRow, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> Dict[str, Any]:
    if await user_service.get_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    try:
        return await user_service.create_user(payload.email, payload.name, payload.password, payload.role)
    except Exception as e:
        logger.error("Error creating user: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the user.")


@router.get("/{user_id}", response_model=UserRow)
async def get_user(user_id: int) -> Dict[str, Any]:
    user = await user_service.get_by_id(user_id)
    if not user:
        raise _NOT_FOUND
    return user


@router.patch("/{user_id}", response_model=UserRow)
async def update_user(
    user_id: int, payload: UserUpdate, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    target = await user_service.get_by_id(user_id)
    if not target:
        raise _NOT_FOUND
    loses_admin = target["role"] == "admin" and (
        (payload.role is not None and payload.role != "admin") or payload.is_active is False
    )
    if loses_admin and user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't remove your own admin role or deactivate yourself. Ask another admin.",
        )
    if loses_admin and await user_service.count_admins(exclude_user_id=user_id) == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This is the last active admin account.")
    try:
        updated = await user_service.update_user(user_id, payload.name, payload.role, payload.is_active)
        if payload.is_active is False:
            await auth_service.revoke_sessions(user_id)
        return updated
    except Exception as e:
        logger.error("Error updating user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update the user.")


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(user_id: int, payload: PasswordReset) -> Response:
    """Sets a new password and signs the account out everywhere."""
    if not await user_service.get_by_id(user_id):
        raise _NOT_FOUND
    try:
        await user_service.set_password(user_id, payload.new_password)
        await auth_service.revoke_sessions(user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error("Error resetting password for user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset the password.")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current_user: Dict[str, Any] = Depends(require_role("admin"))) -> Response:
    """Deletes the account with its runs, run files and uploaded models."""
    target = await user_service.get_by_id(user_id)
    if not target:
        raise _NOT_FOUND
    if user_id == current_user["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't delete your own account.")
    if target["role"] == "admin" and await user_service.count_admins(exclude_user_id=user_id) == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This is the last active admin account.")
    try:
        runs = await db_manager.execute_query(
            "SELECT public_id FROM inference_run WHERE user_id = $1", (user_id,), fetch_all=True
        )
        models = await db_manager.execute_query(
            "SELECT id, file_path FROM ml_model WHERE owner_id = $1", (user_id,), fetch_all=True
        )
        await user_service.delete_user(user_id)  # cascades to runs, media_object, models, sessions
        for r in runs:
            runner.delete_files(r["public_id"])
            await media_service.delete_run_files(r["public_id"])
        for m in models:
            Path(m["file_path"]).unlink(missing_ok=True)
            await run_in_threadpool(manager.forget_custom, f"custom:{m['id']}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error("Error deleting user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete the user.")
