# app/api/deps.py
"""Route guards: who is calling, and what role does this route require.

HTTPBearer (not OAuth2PasswordBearer) because there is no OAuth2 flow here,
just a bearer token issued by /auth/login or /auth/register.

Every guard re-reads the app_user row rather than trusting the token's role
claim, so a role change, a deactivated or deleted account, or a sign-out
everywhere (token_version) takes effect on the very next request instead of
waiting for the token to expire.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.services.user_service import user_service
from app.services.workspace_service import WS_ROLE_LEVEL, workspace_service

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

ROLE_LEVEL = {"user": 1, "admin": 2}

# The console shows these messages verbatim.
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue. Your session may have expired.",
    headers={"WWW-Authenticate": "Bearer"},
)
_ROLE_MESSAGES = {"admin": "Only an administrator can do this."}


async def _user_from_credentials(credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[Dict[str, Any]]:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    user = await user_service.get_by_id(int(payload["sub"]))
    if not user or not user["is_active"] or payload.get("tv") != user["token_version"]:
        return None
    return user


async def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """For public routes that add the caller's progress when signed in. A
    missing or invalid token just means anonymous."""
    return await _user_from_credentials(credentials)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Base guard: any signed-in account."""
    user = await _user_from_credentials(credentials)
    if not user:
        raise _UNAUTHORIZED
    return user


def require_role(minimum: str):
    """Dependency factory: `Depends(require_role("admin"))`. Roles form a
    single ladder (user < admin), so "requires user" also admits admin."""

    async def _guard(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if ROLE_LEVEL.get(user["role"], 0) < ROLE_LEVEL[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_ROLE_MESSAGES.get(minimum, f"This action requires the '{minimum}' role or higher."),
            )
        return user

    return _guard


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user) and user["role"] == "admin"


# ---------------------------------------------------------------- workspaces

_WS_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")


async def workspace_access(workspace_id: int, user: Dict[str, Any], minimum: str = "viewer") -> Dict[str, Any]:
    """{workspace, role, user} if `user` may act at `minimum` in the workspace.
    Non-members get 404 rather than 403, so workspace ids don't leak. System
    admins act as workspace admin everywhere, deactivated workspaces included."""
    ws = await workspace_service.get(workspace_id)
    if not ws:
        raise _WS_NOT_FOUND
    if is_admin(user):
        role = "admin"
    else:
        role = await workspace_service.role_of(workspace_id, user["id"])
        if not role:
            raise _WS_NOT_FOUND
        if not ws["is_active"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This workspace has been deactivated.")
    if WS_ROLE_LEVEL[role] < WS_ROLE_LEVEL[minimum]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This needs the workspace {minimum} role. Ask a workspace admin.",
        )
    return {"workspace": ws, "role": role, "user": user}


def require_workspace(minimum: str = "viewer"):
    """Dependency factory for workspace-scoped routes (cameras, events, ...):
    the console sends the active workspace in the X-Workspace-Id header."""

    async def _guard(
        x_workspace_id: Optional[int] = Header(default=None),
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        if x_workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a workspace first (X-Workspace-Id header)."
            )
        return await workspace_access(x_workspace_id, user, minimum)

    return _guard


def require_workspace_path(minimum: str = "viewer"):
    """The same check for routes with the workspace in the path (/workspaces/{workspace_id}/...)."""

    async def _guard(workspace_id: int, user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        return await workspace_access(workspace_id, user, minimum)

    return _guard
