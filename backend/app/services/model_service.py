# app/services/model_service.py
"""Uploaded Ultralytics weights (ml_model). Built-in public models are in
app/vision/registry.py and never touch the database."""

import logging
from typing import Any, Dict, List, Optional

from app.core.database import db_manager

logger = logging.getLogger(__name__)

# Shared with everyone, plus, when signed in ($1 NULL otherwise), the caller's
# own and those shared with an active workspace the caller belongs to.
_VISIBLE = """(ml.is_public OR ($1::int IS NOT NULL AND (
    ml.owner_id = $1
    OR ml.workspace_id IN (
        SELECT m.workspace_id FROM workspace_member m JOIN workspace w ON w.id = m.workspace_id
        WHERE m.user_id = $1 AND w.is_active
    )
)))"""
_FROM = "FROM ml_model ml LEFT JOIN workspace ws ON ws.id = ml.workspace_id"


class ModelService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def list_visible(self, user_id: Optional[int]) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            f"SELECT ml.*, ws.name AS workspace_name {_FROM} WHERE {_VISIBLE} ORDER BY ml.created_at DESC, ml.id DESC",
            (user_id,),
            fetch_all=True,
        )

    async def usable_for_task(self, user_id: Optional[int], task: Optional[str]) -> List[Dict[str, Any]]:
        """Models a lab tab can offer in its Model picker."""
        if not task:
            return []
        rows = await self.db_manager.execute_query(
            f"SELECT ml.*, ws.name AS workspace_name {_FROM} WHERE {_VISIBLE} AND ml.task = $2 "
            "ORDER BY ml.created_at DESC, ml.id DESC",
            (user_id, task),
            fetch_all=True,
        )
        return [
            {
                "key": f"custom:{m['id']}",
                "name": m["name"],
                "classes": (m["classes"] or [])[:50],
                "public": m["is_public"],
                "workspace": m["workspace_name"],
            }
            for m in rows
        ]

    async def visible_to(self, model_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """The model if `user_id` may use it (same rule as the lists), else None."""
        return await self.db_manager.execute_query(
            f"SELECT ml.*, ws.name AS workspace_name {_FROM} WHERE {_VISIBLE} AND ml.id = $2",
            (user_id, model_id),
            fetch_one=True,
        )

    async def get_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            f"SELECT ml.*, ws.name AS workspace_name {_FROM} WHERE ml.id = $1", (model_id,), fetch_one=True
        )

    async def create_model(
        self,
        owner_id: int,
        project_id: Optional[int],
        name: str,
        task: str,
        file_path: str,
        classes: List[str],
        size_bytes: int,
        is_public: bool,
        workspace_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO ml_model (owner_id, project_id, name, task, file_path, classes, size_bytes, is_public, workspace_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        row = await self.db_manager.execute_query(
            query,
            (owner_id, project_id, name, task, file_path, classes, size_bytes, is_public, workspace_id),
            fetch_one=True,
        )
        return await self.get_model(row["id"])

    async def delete_model(self, model_id: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM ml_model WHERE id = $1", (model_id,), return_rowcount=True
        )


model_service = ModelService()
