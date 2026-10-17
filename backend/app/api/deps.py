# app/api/deps.py
"""Route guards: who is calling, and what role does this route require.

HTTPBearer (not OAuth2PasswordBearer) because there is no OAuth2 flow here,
just a bearer token issued by /auth/login or /auth/register.

Every guard re-reads the app_user row rather than trusting the token's role
claim, so a role change or a deleted account takes effect on the very next
request instead of waiting for the token to expire.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.services.user_service import user_service

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

ROLE_LEVEL = {"user": 1, "admin": 2}

# The console shows these messages verbatim.
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue. Your session may have expired.",
    headers={"WWW-Authenticate": "Bearer"},
)
_ROLE_MESSAGES = {"admin": "Only admins can change the project catalog."}


async def _user_from_credentials(credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[Dict[str, Any]]:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    return await user_service.get_by_id(int(payload["sub"]))


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
