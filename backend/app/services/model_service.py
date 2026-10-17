# app/services/model_service.py
"""Uploaded Ultralytics weights (ml_model). Built-in public models are in
app/vision/registry.py and never touch the database."""

import logging
from typing import Any, Dict, List, Optional

from app.core.database import db_manager

logger = logging.getLogger(__name__)

# Shared with everyone, plus the caller's own when signed in ($1 NULL otherwise).
_VISIBLE = "(is_public OR ($1::int IS NOT NULL AND owner_id = $1))"


class ModelService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def list_visible(self, user_id: Optional[int]) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            f"SELECT * FROM ml_model WHERE {_VISIBLE} ORDER BY created_at DESC, id DESC", (user_id,), fetch_all=True
        )

    async def usable_for_task(self, user_id: Optional[int], task: Optional[str]) -> List[Dict[str, Any]]:
        """Models a lab tab can offer in its Model picker."""
        if not task:
            return []
        rows = await self.db_manager.execute_query(
            f"SELECT * FROM ml_model WHERE {_VISIBLE} AND task = $2 ORDER BY created_at DESC, id DESC",
            (user_id, task),
            fetch_all=True,
        )
        return [
            {"key": f"custom:{m['id']}", "name": m["name"], "classes": (m["classes"] or [])[:50], "public": m["is_public"]}
            for m in rows
        ]

    async def get_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM ml_model WHERE id = $1", (model_id,), fetch_one=True
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
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO ml_model (owner_id, project_id, name, task, file_path, classes, size_bytes, is_public)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """
        return await self.db_manager.execute_query(
            query, (owner_id, project_id, name, task, file_path, classes, size_bytes, is_public), fetch_one=True
        )

    async def delete_model(self, model_id: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM ml_model WHERE id = $1", (model_id,), return_rowcount=True
        )


model_service = ModelService()
