# tests/test_videos.py
"""The workspace video library: uploads, file:/RTSP sources scoped to their
workspace, and deleting. Streaming over RTSP itself is mediamtx's job and is
checked against the running stack, not here."""

import time
import uuid

import pytest

from app.core.config import config
from app.services.lab_service import SAMPLES_DIR


@pytest.fixture(autouse=True)
def mediamtx(monkeypatch):
    monkeypatch.setattr(config, "mediamtx_url", "rtsp://mediamtx:8554")


@pytest.fixture(scope="module")
def two(client, admin_headers):
    def ws():
        w = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Videos {uuid.uuid4().hex[:6]}"}).json()
        return w["id"], {**admin_headers, "X-Workspace-Id": str(w["id"])}
    return ws(), ws()


def _upload(client, headers, name="Dock camera (night).mp4", path=SAMPLES_DIR / "fall.mp4"):
    with open(path, "rb") as f:
        return client.post("/api/cameras/videos", headers=headers, files={"file": (name, f, "video/mp4")})


def test_upload_lists_and_names_safely(client, two):
    (wid, h), _ = two
    r = _upload(client, h)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["name"] == "Dock-camera-night.mp4" and v["size_bytes"] > 0
    assert v["file_source"] == "file:Dock-camera-night.mp4"
    assert v["rtsp_url"] == f"rtsp://mediamtx:8554/files/ws{wid}/Dock-camera-night.mp4"
    assert _upload(client, h).json()["name"] == "Dock-camera-night-2.mp4"  # never overwrites
    lib = client.get("/api/cameras/videos", headers=h).json()
    assert lib["rtsp_enabled"] and [x["name"] for x in lib["videos"]] == ["Dock-camera-night-2.mp4", "Dock-camera-night.mp4"]
    assert {s["rtsp_url"] for s in lib["samples"]} == {"rtsp://mediamtx:8554/street", "rtsp://mediamtx:8554/fall"}


def test_files_that_arent_videos_are_refused(client, two, tmp_path):
    (wid, h), _ = two
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"not a video at all" * 100)
    assert _upload(client, h, "x.mp4", junk).status_code == 422
    assert _upload(client, h, "notes.txt").status_code == 422
    assert not any(p.name.endswith(".part") for p in (config.camera_files_dir / f"ws{wid}").iterdir())


def test_sources_are_scoped_to_their_workspace(client, two):
    (wid_a, ha), (wid_b, hb) = two
    name = _upload(client, ha, "gate.mp4").json()["name"]
    ok = client.post("/api/cameras", headers=ha, json={"name": "Gate file", "source_url": f"file:{name}"})
    assert ok.status_code == 201, ok.text
    ok_rtsp = client.post("/api/cameras", headers=ha, json={"name": "Gate rtsp",
                                                             "source_url": f"rtsp://mediamtx:8554/files/ws{wid_a}/{name}"})
    assert ok_rtsp.status_code == 201, ok_rtsp.text
    # workspace B can't use A's library, neither as file: nor through mediamtx
    assert client.post("/api/cameras", headers=hb, json={"name": "Steal", "source_url": f"file:{name}"}).status_code == 422
    assert client.post("/api/cameras", headers=hb, json={"name": "Steal", "source_url": f"file:ws{wid_a}/{name}"}).status_code == 422
    r = client.post("/api/cameras", headers=hb, json={"name": "Steal", "source_url": f"rtsp://mediamtx:8554/files/ws{wid_a}/{name}"})
    assert r.status_code == 422 and "another workspace" in r.json()["detail"]
    # the samples' streams are anyone's
    assert client.post("/api/cameras", headers=hb, json={"name": "Street", "source_url": "rtsp://mediamtx:8554/street"}).status_code == 201

    # a file: camera reads the library file (it loops like a live camera)
    cam = ok.json()
    client.post(f"/api/cameras/{cam['id']}/start", headers=ha)
    t0 = time.time()
    while time.time() - t0 < 30 and not client.get(f"/api/cameras/{cam['id']}", headers=ha).json()["status"].get("frames_processed"):
        time.sleep(0.3)
    assert client.get(f"/api/cameras/{cam['id']}", headers=ha).json()["status"]["frames_processed"] > 0
    client.post(f"/api/cameras/{cam['id']}/stop", headers=ha)

    lib = client.get("/api/cameras/videos", headers=ha).json()
    assert sorted(next(v for v in lib["videos"] if v["name"] == name)["used_by"]) == ["Gate file", "Gate rtsp"]
    r = client.delete(f"/api/cameras/videos/{name}", headers=ha)
    assert r.status_code == 409 and "Gate" in r.json()["detail"]
    for c in client.get("/api/cameras", headers=ha).json():
        client.delete(f"/api/cameras/{c['id']}", headers=ha)
    assert client.delete(f"/api/cameras/videos/{name}", headers=ha).status_code == 204
    assert client.delete(f"/api/cameras/videos/{name}", headers=ha).status_code == 404
    assert client.delete("/api/cameras/videos/..%2Fx.mp4", headers=ha).status_code == 404


def test_deleting_a_workspace_removes_its_videos(client, admin_headers):
    w = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Gone {uuid.uuid4().hex[:6]}"}).json()
    h = {**admin_headers, "X-Workspace-Id": str(w["id"])}
    assert _upload(client, h, "a.mp4").status_code == 201
    assert (config.camera_files_dir / f"ws{w['id']}").is_dir()
    client.delete(f"/api/workspaces/{w['id']}", headers=admin_headers)
    assert not (config.camera_files_dir / f"ws{w['id']}").exists()
