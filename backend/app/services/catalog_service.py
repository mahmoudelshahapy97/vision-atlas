# app/services/catalog_service.py
"""Domains, task types and technologies."""

import logging
from typing import Any, Dict, List, Optional

import asyncpg

from app.core.database import db_manager

logger = logging.getLogger(__name__)


class CatalogService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def list_domains(self) -> List[Dict[str, Any]]:
        query = """
            SELECT d.id, d.code, d.name, d.slug, COUNT(p.id) AS project_count
            FROM domain d
            LEFT JOIN project p ON p.domain_id = d.id
            GROUP BY d.id
            ORDER BY d.code
        """
        return await self.db_manager.execute_query(query, (), fetch_all=True)

    async def list_task_types(self) -> List[Dict[str, Any]]:
        query = """
            SELECT t.id, t.code, t.name, t.metric,
                   COALESCE((SELECT array_agg(s.text ORDER BY s.position)
                             FROM task_step s WHERE s.task_type_id = t.id), '{}') AS steps,
                   (SELECT COUNT(*) FROM project p WHERE p.task_type_id = t.id) AS project_count
            FROM task_type t
            ORDER BY t.id
        """
        return await self.db_manager.execute_query(query, (), fetch_all=True)

    async def list_technologies(self, limit: int) -> List[Dict[str, Any]]:
        query = """
            SELECT tc.name, COUNT(pt.project_id) AS project_count
            FROM technology tc
            JOIN project_technology pt ON pt.technology_id = tc.id
            GROUP BY tc.id
            ORDER BY project_count DESC, tc.name
            LIMIT $1
        """
        return await self.db_manager.execute_query(query, (limit,), fetch_all=True)

    async def get_domain_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM domain WHERE code = $1", (code,), fetch_one=True
        )

    async def get_task_type_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            "SELECT * FROM task_type WHERE code = $1", (code,), fetch_one=True
        )

    async def get_or_create_technology(self, conn: asyncpg.Connection, name: str) -> int:
        """Technology id by case-insensitive name, inserting it if new. Runs on
        the caller's connection so it joins the caller's transaction."""
        tech_id = await conn.fetchval("SELECT id FROM technology WHERE lower(name) = lower($1)", name)
        if tech_id is None:
            tech_id = await conn.fetchval("INSERT INTO technology (name) VALUES ($1) RETURNING id", name)
        return tech_id


catalog_service = CatalogService()
