# app/services/user_service.py
"""Accounts: lookup, registration, credential checks, admin management and the
bootstrap admin."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import config
from app.core.database import db_manager
from app.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)

_PUBLIC_COLUMNS = "id, email, name, role, is_active, token_version, last_login, created_at, updated_at"


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
        """The user row (without its hash) if the password matches and the
        account is active, else None."""
        user = await self.get_by_email(email)
        if not user or not verify_password(password, user["password_hash"]) or not user["is_active"]:
            return None
        user.pop("password_hash", None)
        return user

    async def check_password(self, user_id: int, password: str) -> bool:
        hashed = await self.db_manager.fetch_value("SELECT password_hash FROM app_user WHERE id = $1", (user_id,))
        return verify_password(password, hashed)

    async def touch_last_login(self, user_id: int) -> None:
        await self.db_manager.execute_query("UPDATE app_user SET last_login = NOW() WHERE id = $1", (user_id,))

    async def bump_token_version(self, user_id: int) -> None:
        """Revokes every access token the account holds."""
        await self.db_manager.execute_query(
            "UPDATE app_user SET token_version = token_version + 1, updated_at = NOW() WHERE id = $1", (user_id,)
        )

    async def set_password(self, user_id: int, password: str) -> None:
        """Also signs the account out everywhere (token_version bump; the
        caller revokes refresh sessions)."""
        await self.db_manager.execute_query(
            "UPDATE app_user SET password_hash = $2, token_version = token_version + 1, updated_at = NOW() "
            "WHERE id = $1",
            (user_id, hash_password(password)),
        )

    # ----------------------------------------------------------------- admin

    async def list_users(
        self, q: Optional[str] = None, role: Optional[str] = None, page: int = 1, per_page: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        where, params = [], []
        if q:
            params.append(f"%{q.lower()}%")
            where.append(f"(email LIKE ${len(params)} OR LOWER(name) LIKE ${len(params)})")
        if role:
            params.append(role)
            where.append(f"role = ${len(params)}")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = await self.db_manager.fetch_value(f"SELECT COUNT(*) FROM app_user {clause}", tuple(params))
        params += [per_page, (page - 1) * per_page]
        rows = await self.db_manager.execute_query(
            f"SELECT {_PUBLIC_COLUMNS} FROM app_user {clause} "
            f"ORDER BY created_at DESC, id DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}",
            tuple(params),
            fetch_all=True,
        )
        return rows or [], total or 0

    async def update_user(
        self,
        user_id: int,
        name: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """A role change or deactivation bumps token_version, so the account's
        open sessions pick up the change (or end) on their next request."""
        current = await self.get_by_id(user_id)
        if not current:
            return None
        revoke = (role is not None and role != current["role"]) or (
            is_active is not None and is_active != current["is_active"]
        )
        return await self.db_manager.execute_query(
            f"""
            UPDATE app_user SET
                name = COALESCE($2, name),
                role = COALESCE($3, role),
                is_active = COALESCE($4, is_active),
                token_version = token_version + $5,
                updated_at = NOW()
            WHERE id = $1
            RETURNING {_PUBLIC_COLUMNS}
            """,
            (user_id, name.strip() if name else None, role, is_active, 1 if revoke else 0),
            fetch_one=True,
        )

    async def delete_user(self, user_id: int) -> bool:
        return bool(
            await self.db_manager.execute_query(
                "DELETE FROM app_user WHERE id = $1", (user_id,), return_rowcount=True
            )
        )

    async def count_admins(self, exclude_user_id: Optional[int] = None) -> int:
        """Active admins, optionally not counting one account (the one about to
        be demoted, deactivated or deleted)."""
        return await self.db_manager.fetch_value(
            "SELECT COUNT(*) FROM app_user WHERE role = 'admin' AND is_active AND id <> COALESCE($1, -1)",
            (exclude_user_id,),
        )

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
