# app/services/user_service.py
"""Accounts: lookup, registration, credential checks and the bootstrap admin."""

import logging
from typing import Any, Dict, Optional

from app.core.config import config
from app.core.database import db_manager
from app.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)

_PUBLIC_COLUMNS = "id, email, name, role, created_at"


class UserService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def get_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            f"SELECT {_PUBLIC_COLUMNS} FROM app_user WHERE id = $1", (user_id,), fetch_one=True
        )

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM app_user WHERE email = $1", (email.lower(),), fetch_one=True
        )

    async def create_user(
        self, email: str, name: str, password: str, role: str = "user"
    ) -> Dict[str, Any]:
        query = f"""
            INSERT INTO app_user (email, name, password_hash, role)
            VALUES ($1, $2, $3, $4)
            RETURNING {_PUBLIC_COLUMNS}
        """
        return await self.db_manager.execute_query(
            query, (email.lower(), name.strip(), hash_password(password), role), fetch_one=True
        )

    async def verify_credentials(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """The user row (without its hash) if the password matches, else None."""
        user = await self.get_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            return None
        user.pop("password_hash", None)
        return user

    async def ensure_bootstrap_admin(self) -> None:
        """Create the ADMIN_EMAIL account on startup if it doesn't exist yet.
        An existing account (and its password) is left alone."""
        if not (config.admin_email and config.admin_password):
            return
        if await self.get_by_email(config.admin_email):
            return
        await self.create_user(config.admin_email, config.admin_name, config.admin_password, role="admin")
        logger.info("Created admin account %s", config.admin_email.lower())


user_service = UserService()
