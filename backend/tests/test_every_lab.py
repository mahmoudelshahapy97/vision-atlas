"""Runs every project's lab on its sample inputs through the real API and run queue.

Slow (a few minutes on CPU). Run with:  pytest -m slow
"""
import json

import pytest

from conftest import wait_run

# labs whose model can't be downloaded in some environments; an error that says so is acceptable
DOWNLOAD_DEPENDENT = {"colorization"}


@pytest.mark.slow
def test_every_project_lab(client, user_headers):
    projects = client.get("/api/projects", params={"size": 200}).json()["items"]
    started = []
    for p in projects:
        lab = p["lab"]
        if not lab.get("samples"):
            continue
        r = client.post("/api/runs", headers=user_headers, data={"project_id": str(p["id"]), "samples": json.dumps(lab["samples"])})
        assert r.status_code == 202, (p["id"], r.text)
        started.append((p["id"], lab["pipeline"], r.json()["public_id"]))
        # keep the queue short so CPU-heavy runs don't pile up
        if len(started) % 2 == 0:
            wait_run(client, user_headers, started[-1][2])
    failures = []
    for pid, pipe, rid in started:
        run = wait_run(client, user_headers, rid)
        if run["status"] != "done" and not (pipe in DOWNLOAD_DEPENDENT and "download" in (run["error"] or "").lower()):
            failures.append((pid, pipe, run["error"]))
        elif run["status"] == "done":
            res = run["result"]
            assert res["summary"] or res["images"] or res["text"], (pid, pipe)
    assert not failures, failures
    assert len(started) >= 75
