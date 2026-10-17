# app/services/project_service.py
"""Catalog projects: filtered listing, facet counts, detail and admin writes.

Every read builds the same nested shape the API returns (domain, task_type,
technologies, and the caller's progress) in one statement, so a page of 200
cards is one round trip.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

import asyncpg

from app.core.database import db_manager
from app.schemas.project_schemas import LEVELS
from app.services.catalog_service import catalog_service
from app.utils.slug_utils import slugify
from app.utils.sql_utils import Params, like_pattern

logger = logging.getLogger(__name__)

# $1 is always the caller's user id (NULL when signed out), so the progress
# join simply matches nothing for anonymous callers.
_PROJECT_SELECT = """
    SELECT p.id, p.title, p.slug, p.description, p.level, p.is_pick, p.pick_reason, p.caution, p.lab,
           p.domain_id, d.code AS domain_code, d.name AS domain_name, d.slug AS domain_slug,
           p.task_type_id, t.code AS task_code, t.name AS task_name, t.metric AS task_metric,
           COALESCE((SELECT array_agg(tc.name ORDER BY pt.position, tc.name)
                     FROM project_technology pt
                     JOIN technology tc ON tc.id = pt.technology_id
                     WHERE pt.project_id = p.id), '{}') AS technologies,
           up.status AS progress_status, up.notes AS progress_notes, up.updated_at AS progress_updated_at
    FROM project p
    JOIN domain d ON d.id = p.domain_id
    JOIN task_type t ON t.id = p.task_type_id
    LEFT JOIN user_project up ON up.project_id = p.id AND up.user_id = $1
"""

_FROM_FILTERED = """
    FROM project p
    JOIN domain d ON d.id = p.domain_id
    JOIN task_type t ON t.id = p.task_type_id
"""

_TECH_MATCH = """EXISTS (SELECT 1 FROM project_technology pt
                         JOIN technology tc ON tc.id = pt.technology_id
                         WHERE pt.project_id = p.id AND {cond})"""

SORTS = {
    "id": "p.id",
    "title": "p.title, p.id",
    "level": "p.level, p.id",
    "level_desc": "p.level DESC, p.id",
}

# Fields a PATCH may set directly; pick_reason/caution/lab may also be cleared.
_UPDATABLE = ("title", "description", "level", "is_pick", "pick_reason", "caution", "lab")
_NULLABLE = ("pick_reason", "caution", "lab")


def _shape(row: Dict[str, Any]) -> Dict[str, Any]:
    """Flat SQL row -> the nested ProjectResponse dict."""
    progress = None
    if row["progress_status"] is not None:
        progress = {
            "project_id": row["id"],
            "status": row["progress_status"],
            "notes": row["progress_notes"],
            "updated_at": row["progress_updated_at"],
        }
    return {
        "id": row["id"],
        "title": row["title"],
        "slug": row["slug"],
        "description": row["description"],
        "level": row["level"],
        "level_name": LEVELS[row["level"]],
        "domain": {"id": row["domain_id"], "code": row["domain_code"],
                   "name": row["domain_name"], "slug": row["domain_slug"]},
        "task_type": {"id": row["task_type_id"], "code": row["task_code"],
                      "name": row["task_name"], "metric": row["task_metric"]},
        "technologies": list(row["technologies"]),
        "is_pick": row["is_pick"],
        "pick_reason": row["pick_reason"],
        "caution": row["caution"],
        "lab": row["lab"],
        "progress": progress,
    }


class ProjectService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    # ------------------------------------------------------------------ filters

    def _where(self, filters: Any, user_id: Optional[int], params: Params, exclude: Optional[str] = None) -> str:
        """WHERE clause for the shared catalog filters. `exclude` drops one
        dimension so its facet shows what switching that option would give.
        A status filter needs a signed-in user; the router checks that."""
        conds: List[str] = []
        if filters.domain and exclude != "domain":
            conds.append(f"d.code = {params.add(filters.domain)}")
        if filters.task and exclude != "task":
            conds.append(f"t.code = {params.add(filters.task)}")
        if filters.level and exclude != "level":
            conds.append(f"p.level = {params.add(filters.level)}")
        if filters.picks:
            conds.append("p.is_pick")
        if filters.tech:
            n = params.add(filters.tech)
            conds.append(_TECH_MATCH.format(cond=f"lower(tc.name) = lower({n})"))
        if filters.q:
            for word in filters.q.lower().split():
                n = params.add(like_pattern(word))
                like = f"LIKE {n} ESCAPE '\\'"
                conds.append(
                    f"(lower(p.title) {like} OR lower(p.description) {like}"
                    f" OR lower(d.name) {like} OR lower(t.name) {like}"
                    f" OR {_TECH_MATCH.format(cond=f'lower(tc.name) {like}')})"
                )
        if filters.status and user_id is not None:
            u = params.add(user_id)
            if filters.status == "active":
                conds.append(f"p.id IN (SELECT project_id FROM user_project WHERE user_id = {u} AND status <> 'idea')")
            elif filters.status == "idea":
                conds.append(f"p.id NOT IN (SELECT project_id FROM user_project WHERE user_id = {u} AND status <> 'idea')")
            else:
                conds.append(
                    f"p.id IN (SELECT project_id FROM user_project WHERE user_id = {u} "
                    f"AND status = {params.add(filters.status)})"
                )
        return ("WHERE " + " AND ".join(conds)) if conds else ""

    async def _count(self, filters: Any, user_id: Optional[int]) -> int:
        params = Params()
        where = self._where(filters, user_id, params)
        return await self.db_manager.fetch_value(f"SELECT COUNT(*) {_FROM_FILTERED} {where}", params.values)

    # ------------------------------------------------------------------ reads

    async def list_projects(
        self, filters: Any, user_id: Optional[int], sort: str, page: int, size: int
    ) -> Dict[str, Any]:
        total = await self._count(filters, user_id)
        params = Params(user_id)
        where = self._where(filters, user_id, params)
        limit, offset = params.add(size), params.add((page - 1) * size)
        query = f"{_PROJECT_SELECT} {where} ORDER BY {SORTS[sort]} LIMIT {limit} OFFSET {offset}"
        rows = await self.db_manager.execute_query(query, params.values, fetch_all=True)
        return {"items": [_shape(r) for r in rows], "total": total, "page": page, "size": size}

    async def facets(self, filters: Any, user_id: Optional[int]) -> Dict[str, Any]:
        async def count_by(column: str, dimension: str) -> Dict[str, int]:
            params = Params()
            where = self._where(filters, user_id, params, exclude=dimension)
            rows = await self.db_manager.execute_query(
                f"SELECT {column} AS key, COUNT(*) AS n {_FROM_FILTERED} {where} GROUP BY {column}",
                params.values,
                fetch_all=True,
            )
            return {str(r["key"]): r["n"] for r in rows}

        by_domain = await count_by("d.code", "domain")
        by_task = await count_by("t.code", "task")
        by_level = await count_by("p.level", "level")
        total = await self._count(filters, user_id)
        domains = await self.db_manager.execute_query("SELECT code FROM domain ORDER BY code", (), fetch_all=True)
        tasks = await self.db_manager.execute_query("SELECT code FROM task_type ORDER BY id", (), fetch_all=True)
        return {
            "total": total,
            "domains": [{"key": r["code"], "count": by_domain.get(r["code"], 0)} for r in domains],
            "task_types": [{"key": r["code"], "count": by_task.get(r["code"], 0)} for r in tasks],
            "levels": [{"key": str(i), "count": by_level.get(str(i), 0)} for i in (1, 2, 3)],
        }

    async def get_project(self, key: str, user_id: Optional[int]) -> Optional[Dict[str, Any]]:
        """Project detail by numeric id or slug, with build steps and prev/next ids."""
        cond = "p.id = $2" if key.isdigit() else "p.slug = $2"
        row = await self.db_manager.execute_query(
            f"{_PROJECT_SELECT} WHERE {cond}", (user_id, int(key) if key.isdigit() else key), fetch_one=True
        )
        if not row:
            return None
        extra = await self.db_manager.execute_query(
            """
            SELECT COALESCE((SELECT array_agg(text ORDER BY position) FROM task_step
                             WHERE task_type_id = $2), '{}') AS steps,
                   (SELECT MAX(id) FROM project WHERE id < $1) AS prev_id,
                   (SELECT MIN(id) FROM project WHERE id > $1) AS next_id
            """,
            (row["id"], row["task_type_id"]),
            fetch_one=True,
        )
        return {**_shape(row), "steps": list(extra["steps"]), "prev_id": extra["prev_id"], "next_id": extra["next_id"]}

    async def list_with_progress(self, user_id: int) -> List[Dict[str, Any]]:
        """Every project the user has a progress row for, most recently touched first."""
        rows = await self.db_manager.execute_query(
            f"{_PROJECT_SELECT} WHERE up.user_id IS NOT NULL ORDER BY up.updated_at DESC", (user_id,), fetch_all=True
        )
        return [_shape(r) for r in rows]

    async def exists(self, project_id: int) -> bool:
        return bool(await self.db_manager.fetch_value("SELECT 1 FROM project WHERE id = $1", (project_id,)))

    async def get_lab_context(self, project_id: int) -> Optional[Dict[str, Any]]:
        """The fields the Vision Lab page and run submission need."""
        return await self.db_manager.execute_query(
            """
            SELECT p.id, p.title, p.description, p.caution, p.lab,
                   d.name AS domain_name, t.metric AS task_metric
            FROM project p
            JOIN domain d ON d.id = p.domain_id
            JOIN task_type t ON t.id = p.task_type_id
            WHERE p.id = $1
            """,
            (project_id,),
            fetch_one=True,
        )

    # ------------------------------------------------------------------ writes

    async def _unique_slug(self, conn: asyncpg.Connection, title: str, exclude_id: Optional[int] = None) -> str:
        base = slugify(title) or "project"
        slug, n = base, 2
        while await conn.fetchval(
            "SELECT 1 FROM project WHERE slug = $1 AND ($2::int IS NULL OR id <> $2)", slug, exclude_id
        ):
            slug, n = f"{base}-{n}", n + 1
        return slug

    async def _set_technologies(self, conn: asyncpg.Connection, project_id: int, names: Sequence[str]) -> None:
        await conn.execute("DELETE FROM project_technology WHERE project_id = $1", project_id)
        for position, name in enumerate(names):
            tech_id = await catalog_service.get_or_create_technology(conn, name)
            await conn.execute(
                "INSERT INTO project_technology (project_id, technology_id, position) VALUES ($1, $2, $3)",
                project_id, tech_id, position,
            )

    async def create_project(self, data: Dict[str, Any], domain_id: int, task_type_id: int) -> int:
        async with self.db_manager.transaction() as conn:
            slug = await self._unique_slug(conn, data["title"])
            project_id = await conn.fetchval(
                """
                INSERT INTO project (title, slug, description, domain_id, task_type_id, level,
                                     is_pick, pick_reason, caution, lab)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                data["title"].strip(), slug, data["description"].strip(), domain_id, task_type_id,
                data["level"], data["is_pick"], data.get("pick_reason") or None, data.get("caution") or None,
                data.get("lab"),
            )
            await self._set_technologies(conn, project_id, data.get("technologies") or [])
        return project_id

    async def update_project(
        self,
        project_id: int,
        data: Dict[str, Any],
        domain_id: Optional[int] = None,
        task_type_id: Optional[int] = None,
    ) -> None:
        """Apply a PATCH. `data` is the exclude_unset dump; None leaves a field
        alone except for pick_reason, caution and lab, where it clears it."""
        params = Params()
        fields: List[str] = []

        def add(column: str, value: Any) -> None:
            fields.append(f"{column} = {params.add(value)}")

        async with self.db_manager.transaction() as conn:
            if domain_id is not None:
                add("domain_id", domain_id)
            if task_type_id is not None:
                add("task_type_id", task_type_id)
            if data.get("title"):
                add("slug", await self._unique_slug(conn, data["title"], exclude_id=project_id))
            for field in _UPDATABLE:
                if field not in data:
                    continue
                value = data[field]
                if field in ("pick_reason", "caution"):
                    value = value or None
                if value is None and field not in _NULLABLE:
                    continue
                add(field, value.strip() if isinstance(value, str) else value)
            fields.append("updated_at = NOW()")
            await conn.execute(
                f"UPDATE project SET {', '.join(fields)} WHERE id = {params.add(project_id)}", *params.values
            )
            if data.get("technologies") is not None:
                await self._set_technologies(conn, project_id, data["technologies"])

    async def delete_project(self, project_id: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM project WHERE id = $1", (project_id,), return_rowcount=True
        )


project_service = ProjectService()
