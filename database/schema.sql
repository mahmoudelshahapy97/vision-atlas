-- ---------------------------------------------------------------------------
-- Vision Project Atlas : schema
--
-- The source of truth for the Atlas schema. Bind-mounted into
-- /docker-entrypoint-initdb.d/ by docker-compose.yml, so Postgres applies it
-- once on the first boot of an empty data volume, followed by seed.sql (the
-- catalog). There is no ORM and no Alembic: what this file says is what the
-- database is. Columns added later also go into SCHEMA_UPGRADES in
-- backend/app/core/database.py so existing volumes pick them up.
--
-- Apply it by hand to a database that already exists:
--
--   psql -h 127.0.0.1 -p 5432 -U atlas -d atlas -f schema.sql
--
-- Safe to re-run: every object is created IF NOT EXISTS.
-- ---------------------------------------------------------------------------

BEGIN;

-- ---------------------------------------------------------------------------
-- domain — one of the 15 catalog areas ("Detection & Retail", "OCR & Documents")
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS domain (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,   -- single letter A..O, used in URLs and filters
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- task_type — the kind of CV problem a project is (detection, OCR, ...)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_type (
    id          SERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,   -- det, seg, ocr, ...
    name        TEXT NOT NULL,
    metric      TEXT NOT NULL           -- how results are usually scored, shown on cards
);

-- ---------------------------------------------------------------------------
-- task_step — the ordered build steps shared by every project of a task type
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_step (
    id            SERIAL PRIMARY KEY,
    task_type_id  INTEGER NOT NULL REFERENCES task_type (id) ON DELETE CASCADE,
    position      SMALLINT NOT NULL,    -- 1-based display order
    text          TEXT NOT NULL,
    UNIQUE (task_type_id, position)
);

-- ---------------------------------------------------------------------------
-- technology — a tool or library a project uses (YOLO26, OpenCV, ...)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS technology (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE    -- matched case-insensitively by the API
);

-- ---------------------------------------------------------------------------
-- project — one catalog entry, with its Vision Lab configuration
--
-- Ids are integers, not UUIDs: the 90 seeded projects keep stable ids 1..90
-- that appear in URLs (/projects/2/lab) and in API responses. New projects
-- continue from the sequence, which seed.sql moves past the seeded ids.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project (
    id            SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    description   TEXT NOT NULL,
    domain_id     INTEGER NOT NULL REFERENCES domain (id),
    task_type_id  INTEGER NOT NULL REFERENCES task_type (id),
    level         SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 3),   -- 1 Beginner, 2 Intermediate, 3 Advanced
    is_pick       BOOLEAN NOT NULL DEFAULT FALSE,                   -- recommended starting points
    pick_reason   TEXT,
    caution       TEXT,
    -- Vision Lab config: {pipeline, support, params, samples, alternatives, note}.
    -- NULL means the project has no lab yet.
    lab           JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_domain ON project (domain_id);
CREATE INDEX IF NOT EXISTS idx_project_task   ON project (task_type_id);
CREATE INDEX IF NOT EXISTS idx_project_level  ON project (level);

-- ---------------------------------------------------------------------------
-- project_technology — which technologies a project lists, in display order
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_technology (
    project_id     INTEGER NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    technology_id  INTEGER NOT NULL REFERENCES technology (id) ON DELETE CASCADE,
    position       SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, technology_id)
);

CREATE INDEX IF NOT EXISTS idx_project_technology_tech ON project_technology (technology_id);

-- ---------------------------------------------------------------------------
-- app_user — a person who signs in to track progress and run labs
--
-- Anyone can register (role 'user'); the bootstrap admin is created by the
-- API from ADMIN_EMAIL / ADMIN_PASSWORD on startup. Admins manage accounts
-- at /api/users.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_user (
    id             SERIAL PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,   -- stored lowercased
    name           TEXT NOT NULL,
    password_hash  TEXT NOT NULL,          -- bcrypt
    role           TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    -- Every access token carries it; bumping it (sign out everywhere, password
    -- change, role change, deactivation) revokes them all at once.
    token_version  INTEGER NOT NULL DEFAULT 1,
    last_login     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- refresh_session — one signed-in device; its refresh token's jti
--
-- Refresh tokens rotate: each use revokes the row and creates a new one.
-- Presenting a rotated jti again (a stolen token replayed) revokes them all.
-- ---------------------------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_refresh_session_user ON refresh_session (user_id) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- user_project — one user's status and notes on one project
--
-- A project the user hasn't touched has no row: status 'idea' with empty
-- notes is the implied default, and the API deletes a row that returns to it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_project (
    user_id     INTEGER NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    project_id  INTEGER NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'idea' CHECK (status IN ('idea', 'planned', 'building', 'done')),
    notes       TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_user_project_status ON user_project (user_id, status);

-- ---------------------------------------------------------------------------
-- workspace — a team's space: its cameras, their events and shared models
--
-- System admins create workspaces and set their limits. Each member has a
-- workspace role: viewer (watch) < operator (run cameras, handle events)
-- < admin (cameras, members). System admins act as admin in every workspace.
-- The catalog, lab runs and boards stay per user, outside any workspace.
-- ---------------------------------------------------------------------------
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

CREATE TABLE IF NOT EXISTS workspace_member (
    workspace_id  INTEGER NOT NULL REFERENCES workspace (id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    role          TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'operator', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_member (user_id);

-- ---------------------------------------------------------------------------
-- ml_model — Ultralytics weights a user uploaded
--
-- The file lives under WEIGHTS_DIR/custom/; file_path is its absolute path
-- inside the api container. Built-in public models are not stored here.
-- Visible to its owner, to everyone when is_public, and to the members of
-- its workspace when workspace_id is set.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml_model (
    id          SERIAL PRIMARY KEY,
    owner_id    INTEGER REFERENCES app_user (id) ON DELETE CASCADE,
    -- SET NULL: deleting a project shouldn't delete weights someone trained.
    project_id  INTEGER REFERENCES project (id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    task        TEXT NOT NULL CHECK (task IN ('detect', 'segment', 'classify', 'pose', 'obb')),
    file_path   TEXT NOT NULL,
    classes     JSONB,                              -- class names, in index order
    size_bytes  BIGINT NOT NULL DEFAULT 0,
    is_public   BOOLEAN NOT NULL DEFAULT FALSE,     -- shared with every user (admins only)
    -- SET NULL: deleting a workspace hands its models back to their owners.
    workspace_id INTEGER REFERENCES workspace (id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_model_owner ON ml_model (owner_id);
CREATE INDEX IF NOT EXISTS idx_ml_model_public ON ml_model (task) WHERE is_public;
CREATE INDEX IF NOT EXISTS idx_ml_model_workspace ON ml_model (workspace_id) WHERE workspace_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- inference_run — one Vision Lab run: its inputs, settings, progress and results
--
-- Files are stored in MinIO under runs/<public_id>/ (in/ and out/), one
-- media_object row each. Without MinIO they stay under MEDIA_DIR/runs/<public_id>/
-- and the JSON refers to them by /media URL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inference_run (
    id           SERIAL PRIMARY KEY,
    public_id    TEXT NOT NULL UNIQUE,              -- uuid4 hex, used in URLs
    user_id      INTEGER NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    -- SET NULL: a run stays in the user's history after its project is deleted.
    project_id   INTEGER REFERENCES project (id) ON DELETE SET NULL,
    pipeline     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'error')),
    progress     DOUBLE PRECISION NOT NULL DEFAULT 0,   -- 0..1
    params       JSONB NOT NULL DEFAULT '{}'::jsonb,    -- resolved settings the pipeline ran with
    inputs       JSONB NOT NULL DEFAULT '[]'::jsonb,    -- [{slot, path, name, kind, url}]
    result       JSONB,                                 -- {summary, images, tables, files, ...}
    error        TEXT,
    duration_ms  INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_run_user_time ON inference_run (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_project   ON inference_run (project_id);
-- Startup recovery and the per-user in-flight limit both look for these.
CREATE INDEX IF NOT EXISTS idx_run_in_flight ON inference_run (user_id) WHERE status IN ('queued', 'running');

-- ---------------------------------------------------------------------------
-- media_object — an image, video or document of a run, stored in MinIO
--
-- url is a presigned GET link (at most 7 days). The API re-signs a link that
-- is about to expire when it returns the run, and saves the new one here. The
-- run's inputs/result JSON carry the same key and link.
-- ---------------------------------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_media_object_run ON media_object (run_id);

COMMIT;

-- ---------------------------------------------------------------------------
-- Notes
--
-- * Enums are TEXT + CHECK, never Postgres ENUM types: adding a value is one
--   ALTER of the constraint instead of an ALTER TYPE that can't run inside a
--   transaction.
-- * No triggers. Services set updated_at = NOW() in their UPDATE statements.
-- * The catalog (domain, task_type, task_step, technology, project,
--   project_technology) is loaded by seed.sql, generated from seed_data.json.
-- ---------------------------------------------------------------------------
