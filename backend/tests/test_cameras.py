# tests/test_cameras.py
"""Cameras: roles, source checks, live pipelines on a looping sample video,
the live WebSocket and its tokens. Needs models-serve (MODELS_URL)."""

import time
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.stream_manager import stream_manager

WHOLE_FRAME = [[0, 0], [1, 0], [1, 1], [0, 1]]


def _user(client, admin_headers, name):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/users", headers=admin_headers, json={"email": email, "name": name, "password": "pass-word-123"})
    assert r.status_code == 201, r.text
    token = client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def site(client, admin_headers):
    """A workspace with an admin, an operator and a viewer, plus an outsider."""
    ws = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Site {uuid.uuid4().hex[:6]}", "max_cameras": 3}).json()
    people = {}
    for role in ("admin", "operator", "viewer", "outsider"):
        email, headers = _user(client, admin_headers, role.title())
        if role != "outsider":
            r = client.post(f"/api/workspaces/{ws['id']}/members", headers=admin_headers, json={"email": email, "role": role})
            assert r.status_code == 201
        people[role] = {**headers, "X-Workspace-Id": str(ws["id"])}
    return {"ws": ws, **people}


def _wait(client, headers, camera_id, check, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/cameras/{camera_id}", headers=headers).json()["status"]
        if check(st):
            return st
        time.sleep(0.5)
    raise AssertionError(f"camera {camera_id} never reached the expected state: {st}")


def test_workspace_header_and_membership_are_required(client, site, user_headers):
    assert client.get("/api/cameras", headers={k: v for k, v in site["viewer"].items() if k != "X-Workspace-Id"}).status_code == 400
    assert client.get("/api/cameras", headers=site["outsider"]).status_code == 404
    assert client.get("/api/cameras", headers=site["viewer"]).status_code == 200


def test_pipelines_offered_to_a_camera(client, site, admin_headers):
    r = client.get("/api/cameras/pipelines", headers=site["viewer"]).json()
    names = {p["name"] for p in r["pipelines"]}
    assert {"detect", "track_count", "restricted_zone"} <= names
    zone = next(p for p in r["pipelines"] if p["name"] == "restricted_zone")
    assert "zone_entry" in zone["events"] and not any(p["name"] == "stride" for p in zone["params"])
    assert "street.mp4" in r["samples"]

    limited = client.post("/api/workspaces", headers=admin_headers,
                          json={"name": f"Limited {uuid.uuid4().hex[:6]}", "enabled_pipelines": ["detect"]}).json()
    headers = {**admin_headers, "X-Workspace-Id": str(limited["id"])}
    assert [p["name"] for p in client.get("/api/cameras/pipelines", headers=headers).json()["pipelines"]] == ["detect"]
    r = client.post("/api/cameras", headers=headers, json={"name": "Gate", "source_url": "sample:street.mp4", "pipeline": "restricted_zone"})
    assert r.status_code == 403


@pytest.mark.parametrize("source", ["/etc/passwd", "file:///etc/passwd", "file:../../etc/passwd", "sample:nope.mp4",
                                    "http://127.0.0.1:8000/x", "http://169.254.169.254/latest", "ftp://cam/x"])
def test_unsafe_or_unknown_sources_are_refused(client, site, source):
    r = client.post("/api/cameras", headers=site["admin"], json={"name": f"Bad {uuid.uuid4().hex[:4]}", "source_url": source})
    assert r.status_code == 422, (source, r.text)


def test_roles_and_credential_redaction(client, site):
    body = {"name": f"Dock {uuid.uuid4().hex[:4]}", "source_url": "rtsp://cam:s3cret@10.1.2.3:554/stream1", "location": "Dock 2"}
    assert client.post("/api/cameras", headers=site["operator"], json=body).status_code == 403
    r = client.post("/api/cameras", headers=site["admin"], json=body)
    assert r.status_code == 201, r.text
    cam = r.json()
    assert cam["source_url"].endswith("s3cret@10.1.2.3:554/stream1") and cam["status"]["state"] == "stopped"
    assert client.post("/api/cameras", headers=site["admin"], json=body).status_code == 409  # same name
    seen = client.get(f"/api/cameras/{cam['id']}", headers=site["viewer"]).json()
    assert seen["source_url"] == "rtsp://cam:***@10.1.2.3:554/stream1"
    assert client.get(f"/api/cameras/{cam['id']}", headers=site["outsider"]).status_code == 404
    assert client.patch(f"/api/cameras/{cam['id']}", headers=site["operator"], json={"name": "x"}).status_code == 403
    assert client.post(f"/api/cameras/{cam['id']}/start", headers=site["viewer"]).status_code == 403
    assert client.delete(f"/api/cameras/{cam['id']}", headers=site["admin"]).status_code == 204


def test_bad_pipeline_settings_are_refused(client, site):
    base = {"name": f"Cam {uuid.uuid4().hex[:4]}", "source_url": "sample:street.mp4"}
    assert client.post("/api/cameras", headers=site["admin"], json={**base, "pipeline": "ocr_document"}).status_code == 422
    r = client.post("/api/cameras", headers=site["admin"], json={**base, "pipeline": "detect", "params": {"conf": "high"}})
    assert r.status_code == 422
    r = client.post("/api/cameras", headers=site["admin"], json={**base, "pipeline": "detect", "params": {"model": "custom:999999"}})
    assert r.status_code == 422


def test_source_preview(client, site):
    r = client.post("/api/cameras/preview", headers=site["admin"], json={"source_url": "sample:street.mp4"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert client.post("/api/cameras/preview", headers=site["viewer"], json={"source_url": "sample:street.mp4"}).status_code == 403


def test_a_live_restricted_zone_camera(client, site):
    r = client.post("/api/cameras", headers=site["admin"], json={
        "name": f"Street {uuid.uuid4().hex[:4]}", "source_url": "sample:street.mp4", "pipeline": "restricted_zone",
        "params": {"zone": WHOLE_FRAME, "classes": ["person"]}, "target_fps": 4,
    })
    assert r.status_code == 201, r.text
    cam = r.json()
    assert cam["params"]["conf"] == 0.25 and cam["params"]["zone"] == WHOLE_FRAME  # completed with defaults

    r = client.post(f"/api/cameras/{cam['id']}/start", headers=site["operator"])
    assert r.status_code == 200 and r.json()["enabled"]
    st = _wait(client, site["viewer"], cam["id"], lambda s: s.get("frames_processed", 0) >= 3 and s.get("recent_events"))
    assert st["state"] == "running" and st["connected"] and "in_zone" in st["metrics"]
    assert st["recent_events"][0]["kind"] == "zone_entry" and st["recent_events"][0]["label"] == "person"

    snap = client.get(f"/api/cameras/{cam['id']}/snapshot", headers=site["viewer"], params={"annotated": True})
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"

    # live view: a token for this camera, frames as JSON header + JPEG
    tok = client.post(f"/api/cameras/{cam['id']}/live-token", headers=site["viewer"]).json()
    assert tok["url"] == f"/api/ws/cameras/{cam['id']}"
    with client.websocket_connect(f"{tok['url']}?token={tok['token']}") as ws:
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "frame":
                break
        assert msg["type"] == "frame" and msg["width"] and "in_zone" in msg["metrics"]
        assert ws.receive_bytes()[:2] == b"\xff\xd8"

    # a token opens only its own camera, and garbage opens nothing
    other = client.post("/api/cameras", headers=site["admin"], json={"name": f"Other {uuid.uuid4().hex[:4]}", "source_url": "sample:fall.mp4"}).json()
    for url in (f"/api/ws/cameras/{other['id']}?token={tok['token']}", f"/api/ws/cameras/{cam['id']}?token=nope"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as ws:
                ws.receive_json()
    assert client.post(f"/api/cameras/{cam['id']}/live-token", headers=site["outsider"]).status_code == 404

    # an edit restarts the running camera with the new settings
    r = client.patch(f"/api/cameras/{cam['id']}", headers=site["admin"], json={"pipeline": "detect", "params": {"classes": ["person"]}})
    assert r.status_code == 200 and r.json()["pipeline"] == "detect"
    _wait(client, site["viewer"], cam["id"], lambda s: "objects" in s.get("metrics", {}))

    r = client.post(f"/api/cameras/{cam['id']}/stop", headers=site["operator"])
    assert r.status_code == 200 and not r.json()["enabled"] and r.json()["status"]["state"] == "stopped"
    for c in (cam, other):
        assert client.delete(f"/api/cameras/{c['id']}", headers=site["admin"]).status_code == 204


def test_the_workspace_camera_limit(client, site):
    made = []
    while True:
        r = client.post("/api/cameras", headers=site["admin"], json={"name": f"Lim {uuid.uuid4().hex[:4]}", "source_url": "sample:fall.mp4"})
        if r.status_code != 201:
            break
        made.append(r.json()["id"])
    assert r.status_code == 409 and "limit of 3" in r.json()["detail"]
    for cid in made:
        client.delete(f"/api/cameras/{cid}", headers=site["admin"])


def test_a_deactivated_workspace_stops_its_cameras(client, site, admin_headers):
    ws = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Paused {uuid.uuid4().hex[:6]}"}).json()
    headers = {**admin_headers, "X-Workspace-Id": str(ws["id"])}
    cam = client.post("/api/cameras", headers=headers, json={"name": "View", "source_url": "sample:fall.mp4"}).json()
    assert client.post(f"/api/cameras/{cam['id']}/start", headers=headers).status_code == 200
    _wait(client, headers, cam["id"], lambda s: s.get("frames_processed", 0) >= 1, timeout=60)
    client.patch(f"/api/workspaces/{ws['id']}", headers=admin_headers, json={"is_active": False})
    client.portal.call(stream_manager.reconcile)  # what the supervisor does every few seconds
    assert client.get(f"/api/cameras/{cam['id']}", headers=headers).json()["status"]["state"] == "stopped"
