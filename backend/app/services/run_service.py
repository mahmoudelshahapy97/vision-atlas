# app/services/run_service.py
"""inference_run rows: submission, history, and the status updates the lab
worker threads make while a pipeline runs (see app/vision/runner.py)."""

import logging
from typing import Any, Dict, List, Optional

from app.core.database import db_manager

logger = logging.getLogger(__name__)

IN_FLIGHT = ("queued", "running")


class RunService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def count_in_flight(self, user_id: int) -> int:
        return await self.db_manager.fetch_value(
            "SELECT COUNT(*) FROM inference_run WHERE user_id = $1 AND status = ANY($2::text[])",
            (user_id, list(IN_FLIGHT)),
        )

    async def create_run(
        self,
        public_id: str,
        user_id: int,
        project_id: Optional[int],
        pipeline: str,
        params: Dict[str, Any],
        inputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO inference_run (public_id, user_id, project_id, pipeline, status, progress, params, inputs)
            VALUES ($1, $2, $3, $4, 'queued', 0, $5, $6)
            RETURNING *
        """
        return await self.db_manager.execute_query(
            query, (public_id, user_id, project_id, pipeline, params, inputs), fetch_one=True
        )

    async def get_by_id(self, run_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM inference_run WHERE id = $1", (run_id,), fetch_one=True
        )

    async def get_by_public_id(self, public_id: str) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM inference_run WHERE public_id = $1", (public_id,), fetch_one=True
        )

    async def list_for_user(self, user_id: int, project_id: Optional[int], limit: int) -> List[Dict[str, Any]]:
        query = """
            SELECT r.*, p.title AS project_title
            FROM inference_run r
            LEFT JOIN project p ON p.id = r.project_id
            WHERE r.user_id = $1 AND ($2::int IS NULL OR r.project_id = $2)
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT $3
        """
        return await self.db_manager.execute_query(query, (user_id, project_id, limit), fetch_all=True)

    async def delete_run(self, run_id: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM inference_run WHERE id = $1", (run_id,), return_rowcount=True
        )

    # ------------------------------------------------------------------ worker updates

    async def mark_running(self, run_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "UPDATE inference_run SET status = 'running' WHERE id = $1 RETURNING *", (run_id,), fetch_one=True
        )

    async def set_progress(self, run_id: int, progress: float) -> None:
        await self.db_manager.execute_query(
            "UPDATE inference_run SET progress = $2 WHERE id = $1 AND status = 'running'", (run_id, progress)
        )

    async def finish(
        self,
        run_id: int,
        status: str,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
        duration_ms: int,
    ) -> None:
        query = """
            UPDATE inference_run
            SET status = $2, result = $3, error = $4, duration_ms = $5, finished_at = NOW(),
                progress = CASE WHEN $2 = 'done' THEN 1 ELSE progress END
            WHERE id = $1
        """
        await self.db_manager.execute_query(query, (run_id, status, result, error, duration_ms))

    async def recover_interrupted(self) -> int:
        """Runs left queued/running by a restart can't resume; mark them failed so users can re-run."""
        return await self.db_manager.execute_query(
            """
            UPDATE inference_run
            SET status = 'error', error = 'The server restarted before this run finished. Please run it again.'
            WHERE status = ANY($1::text[])
            """,
            (list(IN_FLIGHT),),
            return_rowcount=True,
        )


run_service = RunService()
