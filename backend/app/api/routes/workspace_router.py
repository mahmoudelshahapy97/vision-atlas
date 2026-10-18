# app/api/routes/workspace_router.py
"""Workspaces (system admins create and configure them) and their members
(managed by workspace admins)."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user, is_admin, require_role, require_workspace_path
from app.schemas.workspace_schemas import (
    MemberAdd,
    MemberResponse,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.user_service import user_service
from app.services.workspace_service import workspace_service
from app.vision import live

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workspaces"], prefix="/workspaces")


def _check_pipelines(names: Optional[List[str]]) -> Optional[List[str]]:
    if names is None:
        return None
    unknown = sorted(set(names) - set(live.LIVE_ANALYZERS))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Not live pipelines: {', '.join(unknown)}.",
        )
    return sorted(set(names))


async def _check_name(name: Optional[str], exclude_id: Optional[int] = None) -> None:
    if name is not None and await workspace_service.name_taken(name, exclude_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A workspace with this name already exists.")


# ------------------------------------------------------------------ workspaces

@router.get("/mine", response_model=List[WorkspaceResponse])
async def my_workspaces(current_user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """The switcher's list: workspaces the caller belongs to, with their role."""
    return await workspace_service.list_for_user(current_user)


@router.get("/pipelines")
async def live_pipelines(_: Dict[str, Any] = Depends(require_role("admin"))) -> List[Dict[str, str]]:
    """What a workspace's enabled_pipelines may name: the live pipelines."""
    return [{"name": p["name"], "title": p["title"]} for p in live.public_list()]


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(_: Dict[str, Any] = Depends(require_role("admin"))) -> List[Dict[str, Any]]:
    return await workspace_service.list_all()


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, current_user: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    await _check_name(payload.name)
    pipelines = _check_pipelines(payload.enabled_pipelines)
    try:
        ws = await workspace_service.create(
            payload.name,
            payload.description,
            pipelines,
            payload.max_cameras,
            current_user["id"],
        )
        return {**ws, "my_role": "admin"}
    except Exception as e:
        logger.error("Error creating workspace: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the workspace.")


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(access: Dict[str, Any] = Depends(require_workspace_path("viewer"))) -> Dict[str, Any]:
    return {**access["workspace"], "my_role": access["role"]}


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: int, payload: WorkspaceUpdate, _: Dict[str, Any] = Depends(require_role("admin"))
) -> Dict[str, Any]:
    if not await workspace_service.get(workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    fields = payload.model_dump(exclude_unset=True)
    await _check_name(fields.get("name"), workspace_id)
    if "enabled_pipelines" in fields:
        fields["enabled_pipelines"] = _check_pipelines(fields["enabled_pipelines"])
    for required in ("name", "max_cameras", "is_active"):
        if required in fields and fields[required] is None:
            del fields[required]
    try:
        return {**await workspace_service.update(workspace_id, fields), "my_role": "admin"}
    except Exception as e:
        logger.error("Error updating workspace %s: %s", workspace_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update the workspace.")


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(workspace_id: int, _: Dict[str, Any] = Depends(require_role("admin"))) -> Response:
    """Members go with it; models shared with it go back to their owners."""
    if not await workspace_service.delete(workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------- members

@router.get("/{workspace_id}/members", response_model=List[MemberResponse])
async def list_members(
    workspace_id: int, _: Dict[str, Any] = Depends(require_workspace_path("viewer"))
) -> List[Dict[str, Any]]:
    return await workspace_service.members(workspace_id)


@router.post("/{workspace_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    workspace_id: int, payload: MemberAdd, _: Dict[str, Any] = Depends(require_workspace_path("admin"))
) -> Dict[str, Any]:
    user = await user_service.get_by_email(payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account with this email. They can register, or a system admin can create the account.",
        )
    if await workspace_service.role_of(workspace_id, user["id"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{user['email']} is already a member.")
    return await workspace_service.add_member(workspace_id, user["id"], payload.role)


async def _guard_last_admin(workspace_id: int, user_id: int, actor: Dict[str, Any]) -> None:
    """A workspace admin can't leave the workspace without an admin; a system
    admin (who can always manage it) can."""
    if is_admin(actor):
        return
    if await workspace_service.count_admins(workspace_id, exclude_user_id=user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workspace needs at least one admin. Make someone else admin first.",
        )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    workspace_id: int,
    user_id: int,
    payload: MemberUpdate,
    access: Dict[str, Any] = Depends(require_workspace_path("admin")),
) -> Dict[str, Any]:
    current = await workspace_service.member(workspace_id, user_id)
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this workspace.")
    if current["role"] == "admin" and payload.role != "admin":
        await _guard_last_admin(workspace_id, user_id, access["user"])
    return await workspace_service.set_role(workspace_id, user_id, payload.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: int,
    user_id: int,
    access: Dict[str, Any] = Depends(require_workspace_path("viewer")),
) -> Response:
    """Workspace admins remove anyone; any member can leave."""
    if user_id != access["user"]["id"] and access["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a workspace admin can remove members.")
    current = await workspace_service.member(workspace_id, user_id)
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not a member of this workspace.")
    if current["role"] == "admin":
        await _guard_last_admin(workspace_id, user_id, access["user"])
    await workspace_service.remove_member(workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
