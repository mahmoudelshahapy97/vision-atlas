# tests/test_events.py
"""Camera events: recorded from a live pipeline with a snapshot, listed,
handled, pushed over the alerts WebSocket, isolated per workspace and purged.
Needs models-serve (MODELS_URL) and MinIO."""

import time
import uuid

import cv2
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.database import db_manager
from app.services.event_service import event_service
from app.services.object_store import object_store
from app.vision import live
from app.vision.core import fit
from conftest import fetch

WHOLE_FRAME = [[0, 0], [1, 0], [1, 1], [0, 1]]


def _member(client, admin_headers, ws_id, role):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/users", headers=admin_headers, json={"email": email, "name": role, "password": "pass-word-123"})
    client.post(f"/api/workspaces/{ws_id}/members", headers=admin_headers, json={"email": email, "role": role})
    token = client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_id)}


@pytest.fixture(scope="module")
def site(client, admin_headers):
    ws = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Events {uuid.uuid4().hex[:6]}"}).json()
    admin = {**admin_headers, "X-Workspace-Id": str(ws["id"])}
    cam = client.post("/api/cameras", headers=admin, json={
        "name": "Street", "source_url": "sample:street.mp4", "pipeline": "restricted_zone",
        "params": {"zone": WHOLE_FRAME}, "target_fps": 4,
    }).json()
    return {
        "ws": ws, "cam": cam, "admin": admin,
        "operator": _member(client, admin_headers, ws["id"], "operator"),
        "viewer": _member(client, admin_headers, ws["id"], "viewer"),
    }


def _events(client, headers, **params):
    return client.get("/api/events", headers=headers, params=params).json()


def test_a_live_camera_records_events_with_snapshots(client, site):
    tok = client.post("/api/events/alerts-token", headers=site["viewer"]).json()
    with client.websocket_connect(f"{tok['url']}?token={tok['token']}") as ws:
        assert client.post(f"/api/cameras/{site['cam']['id']}/start", headers=site["operator"]).status_code == 200
        msg = ws.receive_json()
        while msg["type"] != "event":
            msg = ws.receive_json()
    pushed = msg["event"]
    assert pushed["kind"] == "zone_entry" and pushed["camera_name"] == "Street" and pushed["status"] == "open"

    t0 = time.time()
    while time.time() - t0 < 60:
        page = _events(client, site["viewer"], kind="zone_entry")
        ev = next((e for e in page["items"] if e["id"] == pushed["id"]), None)
        if ev and ev["snapshot_url"]:
            break
        time.sleep(0.5)
    assert ev and ev["snapshot_url"], page
    assert ev["label"] == "person" and ev["severity"] == "warning" and ev["track_id"] is not None
    snap = fetch(client, ev["snapshot_url"])
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"

    stats = client.get("/api/events/stats", headers=site["viewer"]).json()
    assert stats["open"] >= 1 and stats["last_24h"] >= 1 and stats["cameras"] == 1 and stats["cameras_live"] == 1
    assert "zone_entry" in stats["kinds"]
    client.post(f"/api/cameras/{site['cam']['id']}/stop", headers=site["operator"])


def test_handling_an_event(client, site):
    ev = _events(client, site["viewer"])["items"][0]
    assert client.patch(f"/api/events/{ev['id']}", headers=site["viewer"], json={"status": "acknowledged"}).status_code == 403
    r = client.patch(f"/api/events/{ev['id']}", headers=site["operator"], json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["handled_by_name"] == "operator"
    assert client.patch(f"/api/events/{ev['id']}", headers=site["operator"], json={"status": "nope"}).status_code == 422
    assert all(e["status"] == "acknowledged" for e in _events(client, site["viewer"], status="acknowledged")["items"])
    r = client.patch(f"/api/events/{ev['id']}", headers=site["operator"], json={"status": "open"})
    assert r.json()["handled_by_name"] is None


def test_events_stay_in_their_workspace(client, site, admin_headers):
    ev = _events(client, site["viewer"])["items"][0]
    other = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Other {uuid.uuid4().hex[:6]}"}).json()
    elsewhere = {**admin_headers, "X-Workspace-Id": str(other["id"])}
    assert client.get(f"/api/events/{ev['id']}", headers=elsewhere).status_code == 404
    assert _events(client, elsewhere)["total"] == 0
    # an alerts token is for one workspace
    tok = client.post("/api/events/alerts-token", headers=site["viewer"]).json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/ws/alerts/{other['id']}?token={tok['token']}") as ws:
            ws.receive_json()


def test_retention_purges_old_events_and_their_snapshots(client, site):
    ev = _events(client, site["viewer"])["items"][-1]
    key = f"events/{site['cam']['id']}/{ev['id']}.jpg"
    assert client.portal.call(object_store.list_keys, key) == [key]
    client.portal.call(lambda: db_manager.execute_query(
        "UPDATE camera_event SET occurred_at = NOW() - INTERVAL '40 days' WHERE id = $1", (ev["id"],)))
    assert client.portal.call(event_service.purge) >= 1
    assert client.get(f"/api/events/{ev['id']}", headers=site["viewer"]).status_code == 404
    assert client.portal.call(object_store.list_keys, key) == []


def test_deleting_the_camera_removes_its_events_and_files(client, site):
    cam = site["cam"]
    assert _events(client, site["viewer"], camera_id=cam["id"])["total"] > 0
    assert client.delete(f"/api/cameras/{cam['id']}", headers=site["admin"]).status_code == 204
    assert _events(client, site["viewer"])["total"] == 0
    assert client.portal.call(object_store.list_keys, f"events/{cam['id']}/") == []


def test_live_fall_detection_raises_a_fall(client):
    """The fall analyzer on the fall sample, frame by frame, as a camera would run it."""
    from app.services.lab_service import SAMPLES_DIR

    analyzer = live.build("fall_detection", {})
    cap = cv2.VideoCapture(str(SAMPLES_DIR / "fall.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    events, i = [], 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % 3 == 0:  # about 8 analysed frames a second
                out = analyzer.step(fit(frame, 1280), i / fps)
                events += out.events
                assert set(out.metrics) == {"people", "fallen"}
            i += 1
    finally:
        cap.release()
        analyzer.close()
    assert events and events[0].kind in ("fall", "lying") and events[0].severity == "critical"
