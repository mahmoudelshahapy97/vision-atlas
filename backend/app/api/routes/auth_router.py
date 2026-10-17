# app/api/routes/auth_router.py
"""Register, sign in, and who am I."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.schemas.auth_schemas import AuthUser, LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import auth_service
from app.services.user_service import user_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"], prefix="/auth")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> Dict[str, Any]:
    try:
        if await user_service.get_by_email(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists. Sign in instead.",
            )
        return await auth_service.register(payload.email, payload.name, payload.password)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error registering user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the account."
        )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> Dict[str, Any]:
    result = await auth_service.login(payload.email, payload.password)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    return result


@router.get("/me", response_model=AuthUser)
async def me(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return current_user
