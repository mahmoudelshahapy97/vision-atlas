# app/services/auth_service.py
"""Turns credentials into access tokens."""

import logging
from typing import Any, Dict, Optional

from app.core.security import create_token
from app.services.user_service import user_service

logger = logging.getLogger(__name__)


class AuthService:
    def token_response(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """The /auth/register and /auth/login body: token plus the safe user."""
        return {
            "access_token": create_token(user["id"], user["role"]),
            "token_type": "bearer",
            "user": user,
        }

    async def login(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        user = await user_service.verify_credentials(email, password)
        if not user:
            logger.info("Failed sign-in for %s", email.lower())
            return None
        return self.token_response(user)

    async def register(self, email: str, name: str, password: str) -> Dict[str, Any]:
        user = await user_service.create_user(email, name, password, role="user")
        return self.token_response(user)


auth_service = AuthService()
