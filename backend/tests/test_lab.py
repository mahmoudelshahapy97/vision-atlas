import shutil
from pathlib import Path

from conftest import fetch, wait_run

from app.vision.registry import manager

SAMPLES = Path(__file__).resolve().parents[1] / "app" / "vision" / "samples"


def test_pipelines_and_project_labs(client):
    pipes = client.get("/api/lab/pipelines").json()
    assert len(pipes) >= 79
    names = {p["name"] for p in pipes}
    projects = client.get("/api/projects", params={"size": 200}).json()["items"]
    assert len(projects) == 90 and all(p["lab"] and p["lab"]["pipeline"] in names for p in projects)
    lab = client.get("/api/projects/2/lab").json()
    assert lab["tabs"][0]["name"] == "plate_recognition" and lab["samples"]["media"][0]["name"] == "plate.jpg"
    assert client.get(lab["samples"]["media"][0]["url"]).status_code == 200
    assert len(client.get("/api/lab/support-levels").json()) == 6


def test_run_requires_login(client):
    assert client.post("/api/runs", data={"project_id": "47"}).status_code == 401


def test_sample_run(client, user_headers):
    r = client.post("/api/runs", headers=user_headers, data={"project_id": "47", "samples": '{"image": ["codes.jpg"]}'})
    assert r.status_code == 202, r.text
    run = wait_run(client, user_headers, r.json()["public_id"])
    assert run["status"] == "done", run["error"]
    texts = [row[1] for row in run["result"]["tables"][0]["rows"]]
    assert "https://example.com/asset/CAM-03" in texts
    img = run["result"]["images"][0]["url"]
    assert fetch(client, img).status_code == 200


def test_upload_run_and_param_override(client, user_headers):
    with open(SAMPLES / "omr.jpg", "rb") as f:
        r = client.post("/api/runs", headers=user_headers, data={"project_id": "80", "params": '{"key": "B,E,A,D,B,C,A,A"}'},
                        files={"image": ("sheet.jpg", f, "image/jpeg")})
    run = wait_run(client, user_headers, r.json()["public_id"])
    assert run["status"] == "done", run["error"]
    summary = {s["label"]: s["value"] for s in run["result"]["summary"]}
    assert summary["Score"] == "7/8"   # last answer in the key was changed


def test_validation_errors(client, user_headers):
    assert client.post("/api/runs", headers=user_headers, data={"project_id": "62", "samples": '{"a": ["zidane.jpg"]}'}).status_code == 422
    assert client.post("/api/runs", headers=user_headers, data={"pipeline": "nope"}).status_code == 422
    assert client.post("/api/runs", headers=user_headers, data={"project_id": "47", "samples": '{"image": ["../../config.py"]}'}).status_code == 422
    with open(SAMPLES / "street.mp4", "rb") as f:
        r = client.post("/api/runs", headers=user_headers, data={"project_id": "47"}, files={"image": ("v.mp4", f, "video/mp4")})
    assert r.status_code == 422 and "image" in r.json()["detail"]


def test_user_error_is_reported(client, user_headers):
    r = client.post("/api/runs", headers=user_headers, data={"pipeline": "face_verification",
                                                              "samples": '{"a": ["aerial.jpg"], "b": ["zidane.jpg"]}'})
    run = wait_run(client, user_headers, r.json()["public_id"])
    assert run["status"] == "error" and "No face found in photo A" in run["error"]


def test_custom_model_upload_and_use(client, user_headers, tmp_path):
    # The built-in detector's weights, copied from models-serve (MODELS_URL).
    src = manager.fetch_file("yolo26-detect", tmp_path / "served")
    with open(src, "rb") as f:
        r = client.post("/api/models/upload", headers=user_headers, data={"name": "My detector"}, files={"file": ("best.pt", f)})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["task"] == "detect" and "person" in m["classes"]
    lab = client.get("/api/projects/1/lab", headers=user_headers).json()
    assert any(c["key"] == f"custom:{m['id']}" for c in lab["tabs"][0]["custom_models"])
    r = client.post("/api/runs", headers=user_headers, data={"project_id": "1", "samples": '{"media": ["bus.jpg"]}',
                                                              "params": f'{{"model": "custom:{m["id"]}"}}'})
    run = wait_run(client, user_headers, r.json()["public_id"])
    assert run["status"] == "done" and run["params"]["model"] == f"custom:{m['id']}"
    # a detect model can't be used where a classifier is needed
    bad = client.post("/api/runs", headers=user_headers, data={"project_id": "85", "samples": '{"images": ["bus.jpg"]}',
                                                                "params": f'{{"model": "custom:{m["id"]}"}}'})
    assert bad.status_code == 422
    bad_file = tmp_path / "x.pt"
    bad_file.write_bytes(b"not a model")
    with open(bad_file, "rb") as f:
        assert client.post("/api/models/upload", headers=user_headers, data={"name": "x"}, files={"file": ("x.pt", f)}).status_code == 422
    models = client.get("/api/models", headers=user_headers).json()
    assert any(b["key"] == "yolo26-detect" and b["downloaded"] for b in models["builtin"])
    assert client.delete(f"/api/models/custom/{m['id']}", headers=user_headers).status_code == 204


def test_run_history_and_delete(client, user_headers):
    runs = client.get("/api/runs", headers=user_headers).json()
    assert runs and runs[0]["public_id"]
    done = next(r for r in runs if r["status"] == "done")
    assert client.delete(f"/api/runs/{done['public_id']}", headers=user_headers).status_code == 204
    assert client.get(f"/api/runs/{done['public_id']}", headers=user_headers).status_code == 404
