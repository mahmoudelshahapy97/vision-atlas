# app/api/routes/auth_router.py
"""Register, sign in, refresh, sign out, who am I, and change my password."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.schemas.auth_schemas import (
    AuthUser,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.auth_service import auth_service
from app.services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"], prefix="/auth")


def _client(request: Request) -> Dict[str, Optional[str]]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": request.client.host if request.client else None,
    }


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request) -> Dict[str, Any]:
    try:
        if await user_service.get_by_email(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists. Sign in instead.",
            )
        return await auth_service.register(payload.email, payload.name, payload.password, **_client(request))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error registering user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the account."
        )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request) -> Dict[str, Any]:
    result = await auth_service.login(payload.email, payload.password, **_client(request))
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request) -> Dict[str, Any]:
    """The refresh token travels in the body; the Authorization header is only
    ever the access token."""
    result = await auth_service.refresh(payload.refresh_token, **_client(request))
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has ended. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return result


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest) -> None:
    """Ends this session only; /logout-all ends every session."""
    await auth_service.logout(payload.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(current_user: Dict[str, Any] = Depends(get_current_user)) -> None:
    await auth_service.logout_all(current_user["id"])


@router.get("/me", response_model=AuthUser)
async def me(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return current_user


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePasswordRequest, request: Request, current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Signs out every other session and returns a fresh pair for this one."""
    if not await user_service.check_password(current_user["id"], payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect.")
    try:
        await user_service.set_password(current_user["id"], payload.new_password)
        await auth_service.revoke_sessions(current_user["id"])
        return await auth_service.token_response(await user_service.get_by_id(current_user["id"]), **_client(request))
    except Exception as e:
        logger.error("Error changing password for user %s: %s", current_user["id"], e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not change the password."
        )
