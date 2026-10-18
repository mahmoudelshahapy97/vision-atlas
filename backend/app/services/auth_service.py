# app/services/auth_service.py
"""Sign-in, registration, refresh and sign-out: everything that touches refresh_session."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.core.config import config
from app.core.database import db_manager
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.services.user_service import user_service

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def token_response(
        self, user: Dict[str, Any], user_agent: Optional[str] = None, ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """The /auth/register, /login and /refresh body: a fresh access +
        refresh token pair (the refresh session recorded) plus the safe user."""
        refresh_token, jti = create_refresh_token(user["id"])
        await self.db_manager.execute_query(
            """
            INSERT INTO refresh_session (user_id, jti, expires_at, user_agent, ip_address)
            VALUES ($1, $2, $3, $4, $5)
            """,
            (
                user["id"],
                jti,
                datetime.now(timezone.utc) + timedelta(days=config.refresh_token_expire_days),
                (user_agent or "")[:255] or None,
                ip_address,
            ),
        )
        return {
            "access_token": create_access_token(user["id"], user["role"], user["token_version"]),
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user,
        }

    async def login(self, email: str, password: str, **client: Optional[str]) -> Optional[Dict[str, Any]]:
        user = await user_service.verify_credentials(email, password)
        if not user:
            logger.info("Failed sign-in for %s", email.lower())
            return None
        await user_service.touch_last_login(user["id"])
        return await self.token_response(user, **client)

    async def register(self, email: str, name: str, password: str, **client: Optional[str]) -> Dict[str, Any]:
        user = await user_service.create_user(email, name, password, role="user")
        return await self.token_response(user, **client)

    async def refresh(self, refresh_token: str, **client: Optional[str]) -> Optional[Dict[str, Any]]:
        """Rotates a refresh token: the presented one is revoked and a new pair
        issued. An unknown, expired or revoked jti fails; presenting an already
        rotated one (a replayed, probably stolen token) also revokes the
        account's other sessions."""
        payload = decode_token(refresh_token, "refresh")
        if not payload:
            return None
        session = await self.db_manager.execute_query(
            "SELECT * FROM refresh_session WHERE jti = $1", (payload["jti"],), fetch_one=True
        )
        if not session or session["user_id"] != int(payload["sub"]):
            return None
        if session["revoked_at"] is not None:
            if not session["rotated"]:  # signed out; nothing suspicious
                return None
            logger.warning("Refresh token reuse for user %s; revoking all sessions.", session["user_id"])
            await self.logout_all(session["user_id"])
            return None
        if session["expires_at"] <= datetime.now(timezone.utc):
            return None
        user = await user_service.get_by_id(session["user_id"])
        if not user or not user["is_active"]:
            return None
        revoked = await self.db_manager.execute_query(
            "UPDATE refresh_session SET revoked_at = NOW(), rotated = TRUE WHERE jti = $1 AND revoked_at IS NULL",
            (payload["jti"],),
            return_rowcount=True,
        )
        if not revoked:  # lost a race with another refresh of the same token
            return None
        return await self.token_response(user, **client)

    async def logout(self, refresh_token: Optional[str]) -> None:
        """Revokes this session. A missing or invalid token is already signed out."""
        payload = decode_token(refresh_token or "", "refresh")
        if payload:
            await self.db_manager.execute_query(
                "UPDATE refresh_session SET revoked_at = NOW() WHERE jti = $1 AND revoked_at IS NULL",
                (payload["jti"],),
            )

    async def revoke_sessions(self, user_id: int) -> None:
        await self.db_manager.execute_query(
            "UPDATE refresh_session SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL", (user_id,)
        )

    async def logout_all(self, user_id: int) -> None:
        """Every refresh session revoked and token_version bumped, so the
        account's access tokens stop working too."""
        await self.revoke_sessions(user_id)
        await user_service.bump_token_version(user_id)


auth_service = AuthService()
