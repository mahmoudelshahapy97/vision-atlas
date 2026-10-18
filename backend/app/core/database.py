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
SCHEMA_UPGRADES: tuple = (
    """
    CREATE TABLE IF NOT EXISTS media_object (
        id              SERIAL PRIMARY KEY,
        run_id          INTEGER NOT NULL REFERENCES inference_run (id) ON DELETE CASCADE,
        bucket          TEXT NOT NULL,
        object_key      TEXT NOT NULL UNIQUE,      -- runs/<public_id>/out/03-mask.png
        name            TEXT NOT NULL,             -- file name shown to the user
        kind            TEXT NOT NULL CHECK (kind IN ('image', 'video', 'document')),
        content_type    TEXT NOT NULL,
        size_bytes      BIGINT NOT NULL DEFAULT 0,
        url             TEXT NOT NULL,             -- presigned GET link
        url_expires_at  TIMESTAMPTZ NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_object_run ON media_object (run_id);",
    # accounts: deactivation, token revocation, refresh sessions
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1;",
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;",
    "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
    """
    CREATE TABLE IF NOT EXISTS refresh_session (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
        jti         TEXT NOT NULL UNIQUE,
        expires_at  TIMESTAMPTZ NOT NULL,
        revoked_at  TIMESTAMPTZ,
        rotated     BOOLEAN NOT NULL DEFAULT FALSE,  -- revoked by a refresh (vs. a sign-out)
        user_agent  TEXT,
        ip_address  TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_refresh_session_user ON refresh_session (user_id) WHERE revoked_at IS NULL;",
    # workspaces; models shared with a workspace
    """
    CREATE TABLE IF NOT EXISTS workspace (
        id                 SERIAL PRIMARY KEY,
        name               TEXT NOT NULL UNIQUE,
        slug               TEXT NOT NULL UNIQUE,
        description        TEXT,
        -- Live pipelines its cameras may run; NULL means all of them.
        enabled_pipelines  TEXT[],
        max_cameras        INTEGER NOT NULL DEFAULT 16 CHECK (max_cameras BETWEEN 0 AND 1000),
        is_active          BOOLEAN NOT NULL DEFAULT TRUE,
        created_by         INTEGER REFERENCES app_user (id) ON DELETE SET NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_member (
        workspace_id  INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
        user_id       INTEGER NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
        role          TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'operator', 'admin')),
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (workspace_id, user_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_member (user_id);",
    "ALTER TABLE ml_model ADD COLUMN IF NOT EXISTS workspace_id INTEGER REFERENCES workspace (id) ON DELETE SET NULL;",
    "CREATE INDEX IF NOT EXISTS idx_ml_model_workspace ON ml_model (workspace_id) WHERE workspace_id IS NOT NULL;",
    # cameras
    """
    CREATE TABLE IF NOT EXISTS camera (
        id            SERIAL PRIMARY KEY,
        workspace_id  INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
        name          TEXT NOT NULL,
        -- rtsp(s)://, http(s)://, sample:<lab sample video> or file:<name under CAMERA_FILES_DIR>
        source_url    TEXT NOT NULL,
        location      TEXT,
        -- The operator's intent: enabled cameras run, and are restarted when they fail.
        enabled       BOOLEAN NOT NULL DEFAULT FALSE,
        pipeline      TEXT,                               -- live pipeline; NULL = live view only
        params        JSONB NOT NULL DEFAULT '{}'::jsonb, -- its settings (zones, lines, classes, model)
        target_fps    REAL NOT NULL DEFAULT 5 CHECK (target_fps > 0 AND target_fps <= 30),
        created_by    INTEGER REFERENCES app_user (id) ON DELETE SET NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (workspace_id, name)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_camera_workspace ON camera (workspace_id);",
    "CREATE INDEX IF NOT EXISTS idx_camera_enabled ON camera (enabled) WHERE enabled;",
    # camera events; their snapshots in media_object
    """
    CREATE TABLE IF NOT EXISTS camera_event (
        id               BIGSERIAL PRIMARY KEY,
        workspace_id     INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
        camera_id        INTEGER NOT NULL REFERENCES camera (id) ON DELETE CASCADE,
        pipeline         TEXT NOT NULL,
        kind             TEXT NOT NULL,          -- zone_entry, fall, abandoned, ppe_violation, ...
        label            TEXT NOT NULL,          -- what it is about: "person", "backpack"
        severity         TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),
        track_id         INTEGER,
        confidence       REAL,
        data             JSONB NOT NULL DEFAULT '{}'::jsonb,
        snapshot_key     TEXT,                   -- events/<camera>/<id>.jpg (media_object, or MEDIA_DIR without MinIO)
        status           TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
        handled_by       INTEGER REFERENCES app_user (id) ON DELETE SET NULL,
        handled_at       TIMESTAMPTZ,
        occurred_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_event_workspace_time ON camera_event (workspace_id, occurred_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_event_camera_time ON camera_event (camera_id, occurred_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_event_open ON camera_event (workspace_id) WHERE status = 'open';",
    "ALTER TABLE media_object ALTER COLUMN run_id DROP NOT NULL;",
    "ALTER TABLE media_object ADD COLUMN IF NOT EXISTS event_id BIGINT REFERENCES camera_event (id) ON DELETE CASCADE;",
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'media_object_one_owner') THEN
            ALTER TABLE media_object ADD CONSTRAINT media_object_one_owner CHECK (num_nonnulls(run_id, event_id) = 1);
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_object_event ON media_object (event_id) WHERE event_id IS NOT NULL;",
)


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
