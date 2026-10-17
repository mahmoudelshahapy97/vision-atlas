# app/core/database.py
"""Asyncpg connection pool, schema readiness checks and idempotent upgrades."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

import asyncpg

from app.core.config import config

logger = logging.getLogger(__name__)

connection_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Decode json/jsonb to Python objects and encode them from Python objects.

    Lab config, run params, inputs and results are all JSONB and go straight
    into API responses, so services pass dicts and lists, never JSON strings.
    """
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def init_db_pool() -> asyncpg.Pool:
    """Create the pool, retrying with capped exponential backoff until Postgres is ready."""
    global connection_pool

    if connection_pool is not None and not connection_pool._closed:
        return connection_pool

    delay = config.db_retry_delay_base
    last_error: Optional[Exception] = None

    for attempt in range(1, config.db_max_retries + 1):
        try:
            connection_pool = await asyncpg.create_pool(
                dsn=config.database_dsn,
                min_size=config.db_min_pool_size,
                max_size=config.db_max_pool_size,
                timeout=config.db_timeout,
                command_timeout=config.db_command_timeout,
                init=_init_connection,
            )
            logger.info(
                "Postgres pool ready (%s:%s/%s, %s-%s connections)",
                config.db_host,
                config.db_port,
                config.postgres_db,
                config.db_min_pool_size,
                config.db_max_pool_size,
            )
            return connection_pool
        except Exception as e:
            last_error = e
            logger.warning(
                "Postgres not reachable (attempt %s/%s): %s", attempt, config.db_max_retries, e
            )
            if attempt < config.db_max_retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, config.db_retry_delay_max)

    raise RuntimeError(f"Could not connect to Postgres after {config.db_max_retries} attempts") from last_error


async def close_db_pool() -> None:
    global connection_pool
    if connection_pool is not None and not connection_pool._closed:
        await connection_pool.close()
        logger.info("Postgres pool closed.")
    connection_pool = None


def get_pool() -> Optional[asyncpg.Pool]:
    return connection_pool


async def check_postgres_health() -> bool:
    """Cheap liveness probe used by /health and at startup."""
    pool = get_pool()
    if pool is None or pool._closed:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.warning("Postgres health check failed: %s", e)
        return False


async def wait_for_schema(timeout: float = 60.0) -> bool:
    """Block until database/schema.sql has been applied.

    The Postgres image can report ready while its init scripts are still
    running, so a fresh volume may briefly have a live server with no tables.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    pool = get_pool()
    if pool is None:
        return False

    while loop.time() < deadline:
        try:
            async with pool.acquire() as conn:
                project_exists = await conn.fetchval("SELECT to_regclass('public.project')")
                user_exists = await conn.fetchval("SELECT to_regclass('public.app_user')")
            if project_exists and user_exists:
                return True
        except Exception as e:
            logger.debug("Schema probe failed: %s", e)
        await asyncio.sleep(2)

    logger.error(
        "Tables 'project'/'app_user' not found after %.0fs. "
        "Apply database/schema.sql and database/seed.sql before starting.",
        timeout,
    )
    return False


# schema.sql only runs on the first boot of an empty volume, so a column added
# to it later never reaches an existing database. Each statement here must be
# idempotent: it runs on every start.
SCHEMA_UPGRADES: tuple = ()


async def ensure_schema_upgrades() -> None:
    """Bring an existing database up to the columns the code expects."""
    pool = get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        for statement in SCHEMA_UPGRADES:
            await conn.execute(statement)
    logger.info("Schema upgrades applied (%s statements).", len(SCHEMA_UPGRADES))


class DatabaseManager:
    """Thin query helper so services never touch the pool directly."""

    def _pool(self) -> asyncpg.Pool:
        pool = get_pool()
        if pool is None or pool._closed:
            raise RuntimeError("Database pool is not initialized.")
        return pool

    async def execute_query(
        self,
        query: str,
        params: Sequence[Any] = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
        return_rowcount: bool = False,
    ) -> Union[Optional[Dict[str, Any]], List[Dict[str, Any]], int, None]:
        async with self._pool().acquire() as conn:
            if fetch_one:
                row = await conn.fetchrow(query, *params)
                return dict(row) if row else None
            if fetch_all:
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]

            status = await conn.execute(query, *params)
            if return_rowcount:
                return _rowcount_from_status(status)
            return None

    async def fetch_value(self, query: str, params: Sequence[Any] = ()) -> Any:
        """First column of the first row (COUNT(*), EXISTS, a single id)."""
        async with self._pool().acquire() as conn:
            return await conn.fetchval(query, *params)

    async def execute_many(self, query: str, args: Sequence[Sequence[Any]]) -> None:
        async with self._pool().acquire() as conn:
            await conn.executemany(query, args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """One connection inside BEGIN/COMMIT, for writes that must land together
        (a project and its technology links)."""
        async with self._pool().acquire() as conn:
            async with conn.transaction():
                yield conn


def _rowcount_from_status(status: str) -> int:
    """asyncpg returns command tags like 'DELETE 3' / 'UPDATE 1' / 'INSERT 0 2'."""
    parts = status.split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


db_manager = DatabaseManager()
