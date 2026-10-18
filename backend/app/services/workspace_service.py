# app/services/workspace_service.py
"""Workspaces and their members.

A workspace holds a team's cameras, their events and the models shared with
it. Access is per member with a workspace role (viewer < operator < admin);
system admins act as workspace admin everywhere. See app/api/deps.py for the
guards that use this.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.database import db_manager
from app.utils.slug_utils import slugify

logger = logging.getLogger(__name__)

WS_ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}

# Member and (later) camera counts ride along with every workspace row.
_SELECT = """
    SELECT w.*,
           (SELECT COUNT(*) FROM workspace_member m WHERE m.workspace_id = w.id) AS member_count
    FROM workspace w
"""


class WorkspaceService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    # ------------------------------------------------------------- workspaces

    async def get(self, workspace_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(f"{_SELECT} WHERE w.id = $1", (workspace_id,), fetch_one=True)

    async def list_all(self) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(f"{_SELECT} ORDER BY w.name", fetch_all=True)

    async def list_for_user(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The workspaces the switcher offers, each with the caller's role.
        System admins get every workspace, as admin; members only see active ones."""
        if user["role"] == "admin":
            rows = await self.list_all()
            return [{**r, "my_role": "admin"} for r in rows]
        return await self.db_manager.execute_query(
            f"""
            SELECT w.*, m.role AS my_role,
                   (SELECT COUNT(*) FROM workspace_member x WHERE x.workspace_id = w.id) AS member_count
            FROM workspace w JOIN workspace_member m ON m.workspace_id = w.id AND m.user_id = $1
            WHERE w.is_active
            ORDER BY w.name
            """,
            (user["id"],),
            fetch_all=True,
        )

    async def role_of(self, workspace_id: int, user_id: int) -> Optional[str]:
        return await self.db_manager.fetch_value(
            "SELECT role FROM workspace_member WHERE workspace_id = $1 AND user_id = $2", (workspace_id, user_id)
        )

    async def name_taken(self, name: str, exclude_id: Optional[int] = None) -> bool:
        return bool(
            await self.db_manager.fetch_value(
                "SELECT 1 FROM workspace WHERE (LOWER(name) = LOWER($1) OR slug = $2) AND id <> COALESCE($3, -1)",
                (name.strip(), slugify(name), exclude_id),
            )
        )

    async def create(
        self,
        name: str,
        description: Optional[str],
        enabled_pipelines: Optional[List[str]],
        max_cameras: int,
        created_by: int,
    ) -> Dict[str, Any]:
        row = await self.db_manager.execute_query(
            """
            INSERT INTO workspace (name, slug, description, enabled_pipelines, max_cameras, created_by)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            (name.strip(), slugify(name), description, enabled_pipelines, max_cameras, created_by),
            fetch_one=True,
        )
        return await self.get(row["id"])

    async def update(self, workspace_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """`fields` holds only what the caller sent; enabled_pipelines may be
        set to None on purpose (all pipelines), so it is applied separately."""
        sets, params = [], [workspace_id]
        for col in ("name", "description", "max_cameras", "is_active", "enabled_pipelines"):
            if col in fields:
                params.append(fields[col].strip() if col == "name" else fields[col])
                sets.append(f"{col} = ${len(params)}")
                if col == "name":
                    params.append(slugify(fields[col]))
                    sets.append(f"slug = ${len(params)}")
        if sets:
            await self.db_manager.execute_query(
                f"UPDATE workspace SET {', '.join(sets)}, updated_at = NOW() WHERE id = $1", tuple(params)
            )
        return await self.get(workspace_id)

    async def delete(self, workspace_id: int) -> bool:
        return bool(
            await self.db_manager.execute_query(
                "DELETE FROM workspace WHERE id = $1", (workspace_id,), return_rowcount=True
            )
        )

    # ---------------------------------------------------------------- members

    async def members(self, workspace_id: int) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            """
            SELECT u.id AS user_id, u.email, u.name, u.is_active, m.role, m.created_at
            FROM workspace_member m JOIN app_user u ON u.id = m.user_id
            WHERE m.workspace_id = $1
            ORDER BY CASE m.role WHEN 'admin' THEN 0 WHEN 'operator' THEN 1 ELSE 2 END, u.name
            """,
            (workspace_id,),
            fetch_all=True,
        )

    async def member(self, workspace_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            """
            SELECT u.id AS user_id, u.email, u.name, u.is_active, m.role, m.created_at
            FROM workspace_member m JOIN app_user u ON u.id = m.user_id
            WHERE m.workspace_id = $1 AND m.user_id = $2
            """,
            (workspace_id, user_id),
            fetch_one=True,
        )

    async def add_member(self, workspace_id: int, user_id: int, role: str) -> Dict[str, Any]:
        await self.db_manager.execute_query(
            "INSERT INTO workspace_member (workspace_id, user_id, role) VALUES ($1, $2, $3)",
            (workspace_id, user_id, role),
        )
        return await self.member(workspace_id, user_id)

    async def set_role(self, workspace_id: int, user_id: int, role: str) -> Optional[Dict[str, Any]]:
        await self.db_manager.execute_query(
            "UPDATE workspace_member SET role = $3, updated_at = NOW() WHERE workspace_id = $1 AND user_id = $2",
            (workspace_id, user_id, role),
        )
        return await self.member(workspace_id, user_id)

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        return bool(
            await self.db_manager.execute_query(
                "DELETE FROM workspace_member WHERE workspace_id = $1 AND user_id = $2",
                (workspace_id, user_id),
                return_rowcount=True,
            )
        )

    async def count_admins(self, workspace_id: int, exclude_user_id: Optional[int] = None) -> int:
        return await self.db_manager.fetch_value(
            "SELECT COUNT(*) FROM workspace_member WHERE workspace_id = $1 AND role = 'admin' "
            "AND user_id <> COALESCE($2, -1)",
            (workspace_id, exclude_user_id),
        )


workspace_service = WorkspaceService()
