# app/services/progress_service.py
"""A user's status and notes per project, and the numbers on their board."""

import logging
from typing import Any, Dict, Optional

from app.core.database import db_manager
from app.schemas.progress_schemas import STATUSES

logger = logging.getLogger(__name__)

_RETURNING = "RETURNING project_id, status, notes, updated_at"


class ProgressService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def get(self, user_id: int, project_id: int) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT project_id, status, notes, updated_at FROM user_project WHERE user_id = $1 AND project_id = $2",
            (user_id, project_id),
            fetch_one=True,
        )

    async def set_progress(
        self, user_id: int, project_id: int, status: Optional[str], notes: Optional[str]
    ) -> Dict[str, Any]:
        """Merge status and/or notes into the user's row.

        An untouched project needs no row: when the result is status 'idea'
        with blank notes the row is deleted (or never created), which keeps
        the table to real progress.
        """
        current = await self.get(user_id, project_id)
        new_status = status if status is not None else (current["status"] if current else "idea")
        new_notes = notes if notes is not None else (current["notes"] if current else "")

        if new_status == "idea" and not new_notes.strip():
            if current:
                await self.reset(user_id, project_id)
            return {"project_id": project_id, "status": "idea", "notes": "", "updated_at": None}

        query = f"""
            INSERT INTO user_project (user_id, project_id, status, notes)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, project_id)
            DO UPDATE SET status = EXCLUDED.status, notes = EXCLUDED.notes, updated_at = NOW()
            {_RETURNING}
        """
        return await self.db_manager.execute_query(
            query, (user_id, project_id, new_status, new_notes), fetch_one=True
        )

    async def reset(self, user_id: int, project_id: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM user_project WHERE user_id = $1 AND project_id = $2",
            (user_id, project_id),
            return_rowcount=True,
        )

    async def stats(self, user_id: int) -> Dict[str, Any]:
        total = await self.db_manager.fetch_value("SELECT COUNT(*) FROM project")
        counts = dict.fromkeys(STATUSES, 0)
        rows = await self.db_manager.execute_query(
            "SELECT status, COUNT(*) AS n FROM user_project WHERE user_id = $1 GROUP BY status",
            (user_id,),
            fetch_all=True,
        )
        for r in rows:
            counts[r["status"]] = r["n"]
        # Projects without a row are ideas too.
        counts["idea"] = total - counts["planned"] - counts["building"] - counts["done"]

        by_domain = await self.db_manager.execute_query(
            """
            SELECT d.code, d.name,
                   COUNT(DISTINCT p.id) AS total,
                   COUNT(up.project_id) FILTER (WHERE up.status <> 'idea') AS started,
                   COUNT(up.project_id) FILTER (WHERE up.status = 'done') AS done
            FROM domain d
            JOIN project p ON p.domain_id = d.id
            LEFT JOIN user_project up ON up.project_id = p.id AND up.user_id = $1
            GROUP BY d.code, d.name
            ORDER BY d.code
            """,
            (user_id,),
            fetch_all=True,
        )
        recent = await self.db_manager.execute_query(
            """
            SELECT project_id, status, notes, updated_at FROM user_project
            WHERE user_id = $1 AND status <> 'idea'
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (user_id,),
            fetch_all=True,
        )
        return {"total": total, "counts": counts, "by_domain": by_domain, "recent": recent}


progress_service = ProgressService()
