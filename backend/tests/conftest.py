# tests/conftest.py
"""API tests run against a real, throwaway PostgreSQL database.

Before the app is imported, a fresh database (TEST_POSTGRES_DB, default
atlas_test) is created on the server in DB_HOST/DB_PORT and loaded from
database/schema.sql + seed.sql, the same files Postgres applies on first boot.
When no server is reachable, every test that needs the API is skipped; the
pure unit tests (test_security.py) still run.
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_POSTGRES_DB", "atlas_test")
SQL_DIR = Path(os.environ.get("SQL_DIR", Path(__file__).resolve().parents[2] / "database"))

os.environ["POSTGRES_DB"] = TEST_DB
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "atlas")
os.environ.setdefault("POSTGRES_PASSWORD", "atlas")
os.environ.setdefault("DB_MAX_RETRIES", "3")
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["LOG_FILE_PATH"] = ""
os.environ["MEDIA_DIR"] = str(Path(tempfile.mkdtemp()) / "media")
os.environ["CAMERA_FILES_DIR"] = tempfile.mkdtemp()  # never the stack's /data volume
os.environ.setdefault("LAB_WORKERS", "2")
os.environ.setdefault("MAX_RUNS_IN_FLIGHT", "50")


async def _create_test_database() -> None:
    import asyncpg

    conn_args = dict(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        timeout=5,
    )
    admin = await asyncpg.connect(database="postgres", **conn_args)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(database=TEST_DB, **conn_args)
    try:
        await conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        await conn.execute((SQL_DIR / "seed.sql").read_text(encoding="utf-8"))
    finally:
        await conn.close()


def _prepare() -> str | None:
    """None when the test database is ready, else why it isn't."""
    if not (SQL_DIR / "schema.sql").exists():
        return f"database/schema.sql not found in {SQL_DIR} (set SQL_DIR)."
    try:
        asyncio.run(_create_test_database())
    except Exception as e:
        return f"No database reachable ({os.environ['DB_HOST']}:{os.environ['DB_PORT']}): {e}"
    return None


_SKIP_REASON = _prepare()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    if _SKIP_REASON:
        pytest.skip(_SKIP_REASON)
    with TestClient(app) as c:
        yield c


def _token(client, email, password, name="Tester", register=True):
    if register:
        r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
        if r.status_code == 201:
            return r.json()["access_token"]
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def user_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'user@example.com', 'user-pass-123')}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'admin@example.com', 'admin-pass-123', register=False)}"}


def fetch(client, url, **kw):
    """GET a file link from a run: a presigned MinIO URL, or /media/... on the API."""
    if url.startswith("http"):
        import httpx

        return httpx.get(url, timeout=30, **kw)
    return client.get(url, **kw)


def wait_run(client, headers, public_id, timeout=600):
    """Poll a run until it finishes."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/runs/{public_id}", headers=headers).json()
        if r["status"] in ("done", "error"):
            return r
        time.sleep(0.3)
    raise AssertionError(f"run {public_id} did not finish")
