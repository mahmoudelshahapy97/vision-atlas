# app/services/camera_service.py
"""Cameras: rows in a workspace. Their runtime (the worker reading and
analysing the stream) is app/services/stream_manager.py."""

import logging
from typing import Any, Dict, List, Optional

from app.core.database import db_manager

logger = logging.getLogger(__name__)

_COLUMNS = ("name", "source_url", "location", "pipeline", "params", "target_fps")


class CameraService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def list(self, workspace_id: int) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM camera WHERE workspace_id = $1 ORDER BY name", (workspace_id,), fetch_all=True
        )

    async def get(self, camera_id: int, workspace_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """With `workspace_id`, a camera of another workspace is None (a 404 for the caller)."""
        return await self.db_manager.execute_query(
            "SELECT * FROM camera WHERE id = $1 AND ($2::int IS NULL OR workspace_id = $2)",
            (camera_id, workspace_id),
            fetch_one=True,
        )

    async def count(self, workspace_id: int) -> int:
        return await self.db_manager.fetch_value("SELECT COUNT(*) FROM camera WHERE workspace_id = $1", (workspace_id,))

    async def name_taken(self, workspace_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        return bool(
            await self.db_manager.fetch_value(
                "SELECT 1 FROM camera WHERE workspace_id = $1 AND LOWER(name) = LOWER($2) AND id <> COALESCE($3, -1)",
                (workspace_id, name.strip(), exclude_id),
            )
        )

    async def create(self, workspace_id: int, fields: Dict[str, Any], created_by: int) -> Dict[str, Any]:
        return await self.db_manager.execute_query(
            """
            INSERT INTO camera (workspace_id, name, source_url, location, pipeline, params, target_fps, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            (
                workspace_id,
                fields["name"].strip(),
                fields["source_url"],
                fields.get("location"),
                fields.get("pipeline"),
                fields.get("params") or {},
                fields.get("target_fps", 5.0),
                created_by,
            ),
            fetch_one=True,
        )

    async def update(self, camera_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sets, params = [], [camera_id]
        for col in _COLUMNS:
            if col in fields:
                params.append(fields[col].strip() if col == "name" else fields[col])
                sets.append(f"{col} = ${len(params)}")
        if not sets:
            return await self.get(camera_id)
        return await self.db_manager.execute_query(
            f"UPDATE camera SET {', '.join(sets)}, updated_at = NOW() WHERE id = $1 RETURNING *",
            tuple(params),
            fetch_one=True,
        )

    async def set_enabled(self, camera_id: int, enabled: bool) -> None:
        await self.db_manager.execute_query(
            "UPDATE camera SET enabled = $2, updated_at = NOW() WHERE id = $1", (camera_id, enabled)
        )

    async def delete(self, camera_id: int) -> bool:
        return bool(
            await self.db_manager.execute_query("DELETE FROM camera WHERE id = $1", (camera_id,), return_rowcount=True)
        )

    # ---------------------------------------------------------- stream manager

    _RUNNABLE = """
        SELECT c.*, m.file_path AS model_path
        FROM camera c
        JOIN workspace w ON w.id = c.workspace_id AND w.is_active
        LEFT JOIN ml_model m ON c.params ? 'model' AND c.params->>'model' = 'custom:' || m.id
        WHERE c.enabled
    """

    async def list_runnable(self) -> List[Dict[str, Any]]:
        """Enabled cameras of active workspaces, with their uploaded model's weights path."""
        return await self.db_manager.execute_query(f"{self._RUNNABLE} ORDER BY c.id", fetch_all=True)

    async def get_runnable(self, camera_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(f"{self._RUNNABLE} AND c.id = $1", (camera_id,), fetch_one=True)


camera_service = CameraService()
