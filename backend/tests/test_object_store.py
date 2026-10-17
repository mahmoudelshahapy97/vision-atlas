"""Run files in MinIO with presigned links in media_object.

Needs a MinIO reachable at MINIO_ENDPOINT, with MINIO_PUBLIC_URL pointing at
the same server as seen from the tests (http://minio:9000 inside compose).
Skipped when MINIO_ENDPOINT is empty.
"""

import asyncio
import os

import asyncpg
import pytest

from conftest import fetch, wait_run

from app.core.config import config
from app.services.object_store import object_store
from app.vision import runner

needs_minio = pytest.mark.skipif(not os.environ.get("MINIO_ENDPOINT"), reason="MINIO_ENDPOINT is not set")


def _sql(query, *args):
    async def go():
        conn = await asyncpg.connect(
            host=config.db_host, port=config.db_port, user=config.postgres_user,
            password=config.postgres_password, database=config.postgres_db,
        )
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(go())


def _links(run):
    res = run["result"] or {}
    out = [(i["key"], i["url"]) for i in run["inputs"]]
    out += [(e["key"], e["url"]) for e in res.get("images", []) + res.get("files", [])]
    if res.get("video"):
        out += [(res["video"]["key"], res["video"]["url"]), (res["video"]["poster_key"], res["video"]["poster"])]
    return out


@needs_minio
def test_image_run_is_stored_in_minio(client, user_headers):
    r = client.post("/api/runs", headers=user_headers, data={"project_id": "47", "samples": '{"image": ["codes.jpg"]}'})
    assert r.status_code == 202, r.text
    pid = r.json()["public_id"]
    assert r.json()["inputs"][0]["url"].startswith(config.minio_public_url)
    run = wait_run(client, user_headers, pid)
    assert run["status"] == "done", run["error"]

    links = _links(run)
    assert {k.split("/")[2] for k, _ in links} == {"in", "out"}
    for key, url in links:
        assert key.startswith(f"runs/{pid}/")
        assert url.startswith(f"{config.minio_public_url}/{config.minio_bucket}/{key}?") and "X-Amz-Signature" in url
    img = fetch(client, run["result"]["images"][0]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    csv = fetch(client, run["result"]["files"][0]["url"])
    assert csv.status_code == 200 and 'attachment; filename="codes.csv"' in csv.headers["content-disposition"]

    rows = _sql(
        "SELECT m.object_key, m.kind, m.url, m.url_expires_at > NOW() + interval '6 days' AS fresh "
        "FROM media_object m JOIN inference_run r ON r.id = m.run_id WHERE r.public_id = $1", pid)
    assert {row["object_key"] for row in rows} == {k for k, _ in links}
    assert {row["kind"] for row in rows} == {"image", "document"}
    assert all(row["fresh"] for row in rows)
    # Scratch copies are gone once everything is in the store.
    assert not runner.run_dir(pid).exists()

    # A link about to expire is re-signed on read, and the new one saved.
    _sql("UPDATE media_object SET url = 'stale', url_expires_at = NOW() + interval '5 minutes' "
         "WHERE run_id = (SELECT id FROM inference_run WHERE public_id = $1)", pid)
    again = client.get(f"/api/runs/{pid}", headers=user_headers).json()
    assert all(url.startswith("http") for _, url in _links(again))
    assert not _sql("SELECT 1 FROM media_object WHERE url = 'stale' OR url_expires_at < NOW() + interval '1 day'")
    listed = next(x for x in client.get("/api/runs", headers=user_headers).json() if x["public_id"] == pid)
    assert listed["thumbnail"].startswith(config.minio_public_url)

    assert client.delete(f"/api/runs/{pid}", headers=user_headers).status_code == 204
    assert asyncio.run(object_store.list_keys(f"runs/{pid}/")) == []
    assert not _sql("SELECT 1 FROM media_object WHERE object_key LIKE $1", f"runs/{pid}/%")


@needs_minio
def test_video_run_streams_from_minio(client, user_headers):
    r = client.post("/api/runs", headers=user_headers, data={"pipeline": "video_anomaly", "samples": '{"video": ["street.mp4"]}'})
    assert r.status_code == 202, r.text
    run = wait_run(client, user_headers, r.json()["public_id"])
    assert run["status"] == "done", run["error"]
    video = run["result"]["video"]
    assert video["poster_key"].endswith(".poster.jpg")
    part = fetch(client, video["url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-type"] == "video/mp4"
    assert fetch(client, video["poster"]).status_code == 200


def test_disk_fallback_without_minio(client, user_headers, monkeypatch):
    monkeypatch.setattr(config, "minio_endpoint", "")
    r = client.post("/api/runs", headers=user_headers, data={"project_id": "47", "samples": '{"image": ["codes.jpg"]}'})
    pid = r.json()["public_id"]
    run = wait_run(client, user_headers, pid)
    assert run["status"] == "done", run["error"]
    for entry in run["inputs"] + run["result"]["images"] + run["result"]["files"]:
        assert entry["url"].startswith(f"/media/runs/{pid}/") and "key" not in entry
    assert client.get(run["result"]["images"][0]["url"]).status_code == 200
    assert not _sql("SELECT 1 FROM media_object WHERE object_key LIKE $1", f"runs/{pid}/%")
    assert client.delete(f"/api/runs/{pid}", headers=user_headers).status_code == 204
    assert not runner.run_dir(pid).exists()
