import hashlib
import io
import json
import uuid

import cv2
import numpy as np
import pytest

from conftest import AUTH


def _post(client, path, meta=None, files=None):
    return client.post(path, headers=AUTH, data={"meta": json.dumps(meta or {})}, files=files)


def _npy(a) -> bytes:
    buf = io.BytesIO()
    np.save(buf, a)
    return buf.getvalue()


def test_health_is_open_and_routes_need_the_token(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["device"]
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    models = client.get("/v1/models", headers=AUTH).json()
    keys = {m["key"] for m in models["models"]}
    assert {"yolo26-detect", "yoloe26", "sam2", "easyocr", "lama", "midas", "latex-ocr"} <= keys


def test_predict_detect(client, bus_jpg):
    r = _post(client, "/v1/predict", {"model": "yolo26-detect", "kwargs": {"conf": 0.4, "save": True, "project": "/tmp/x"}},
              [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert len(res) == 1
    names = res[0]["names"]
    found = [names[str(int(c))] for c in res[0]["boxes"]["cls"]]
    assert found.count("person") >= 3 and "bus" in found


def test_batch_and_embed(client, bus_jpg):
    files = [("image", ("a.jpg", bus_jpg)), ("image", ("b.jpg", bus_jpg))]
    r = _post(client, "/v1/predict", {"model": "yolo26-detect", "batch": True}, files)
    assert len(r.json()["results"]) == 2
    e = _post(client, "/v1/embed", {"model": "yolo26-classify"}, files)
    assert e.status_code == 200, e.text
    E = np.load(io.BytesIO(e.content))
    assert E.shape[0] == 2 and E.dtype == np.float32 and np.allclose(E[0], E[1], atol=1e-3)


def test_tracking_session_keeps_ids(client, bus_jpg):
    sid = uuid.uuid4().hex
    ids = []
    for _ in range(3):
        r = _post(client, "/v1/track", {"model": "yolo26-detect", "session": sid, "kwargs": {"conf": 0.3}},
                  [("image", ("f.jpg", bus_jpg))])
        assert r.status_code == 200, r.text
        ids.append(r.json()["results"][0]["boxes"]["id"])
    assert ids[-1] and set(ids[-1]) == set(ids[1])  # same people, same ids across frames
    assert client.delete(f"/v1/track/{sid}", headers=AUTH).status_code == 204
    bad = _post(client, "/v1/track", {"model": "yolo26-detect", "session": sid, "tracker": "../../etc/x.yaml"},
                [("image", ("f.jpg", bus_jpg))])
    assert bad.status_code == 400


def test_errors(client, bus_jpg):
    r = _post(client, "/v1/predict", {"model": "nope"}, [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 503 and r.json()["error"] == "model"
    r = _post(client, "/v1/predict", {"model": "yolo26-detect"}, [("image", ("bus.jpg", b"not an image"))])
    assert r.status_code == 400 and r.json()["error"] == "input"
    r = client.post("/v1/predict", headers=AUTH, data={"meta": "{bad"}, files=[("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 400


def test_custom_model_push_inspect_and_use(client, bus_jpg):
    path = client.get("/v1/models/yolo26-detect/file", headers=AUTH)
    assert path.status_code == 200 and len(path.content) > 1_000_000
    weights = path.content
    sha = hashlib.sha256(weights).hexdigest()
    key = "custom:9001"

    info = client.post("/v1/custom/inspect", headers=AUTH, files={"file": ("best.pt", weights)}).json()
    assert info["task"] == "detect" and "person" in info["names"]
    assert client.post("/v1/custom/inspect", headers=AUTH, files={"file": ("x.pt", b"junk")}).status_code == 422

    client.delete(f"/v1/custom/{key}", headers={**AUTH, "X-Content-SHA256": sha})  # start without the file
    meta = {"model": key, "custom_sha": sha}
    r = _post(client, "/v1/predict", meta, [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 409 and r.json()["error"] == "custom_missing"
    bad = client.put(f"/v1/custom/{key}", headers={**AUTH, "X-Content-SHA256": "0" * 64}, content=weights)
    assert bad.status_code == 422
    ok = client.put(f"/v1/custom/{key}", headers={**AUTH, "X-Content-SHA256": sha}, content=weights)
    assert ok.status_code == 200, ok.text
    r = _post(client, "/v1/predict", meta, [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 200 and r.json()["results"][0]["boxes"]["xyxy"]
    assert client.delete(f"/v1/custom/{key}", headers=AUTH).status_code == 204
    assert client.put("/v1/custom/../../x", headers={**AUTH, "X-Content-SHA256": sha}, content=b"x").status_code in (404, 422)


@pytest.mark.slow
def test_heavier_models(client, bus_jpg):
    img = cv2.imdecode(np.frombuffer(bus_jpg, np.uint8), cv2.IMREAD_COLOR)
    r = _post(client, "/v1/yoloe", {"model": "yoloe26", "prompts": ["bus", "person"], "kwargs": {"conf": 0.2}},
              [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 200 and r.json()["results"][0]["masks"]["xy"]
    h, w = img.shape[:2]
    r = _post(client, "/v1/predict", {"model": "sam2", "mask_data": True, "kwargs": {"points": [[[w / 2, h / 2]]], "labels": [[1]]}},
              [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 200 and r.json()["results"][0]["masks"]["data"]
    r = _post(client, "/v1/ocr", {"langs": ["en"]}, [("image", ("bus.jpg", bus_jpg))])
    assert r.status_code == 200 and isinstance(r.json()["items"], list)

    tile = np.ascontiguousarray(img[:64, :64])
    up = client.post("/v1/realesrgan", headers=AUTH, files={"image": ("image.npy", _npy(tile))})
    assert np.load(io.BytesIO(up.content)).shape == (256, 256, 3)
    small = np.ascontiguousarray(img[:256, :256])
    mask = np.zeros((256, 256), np.uint8)
    mask[100:150, 100:150] = 1
    lama = client.post("/v1/lama", headers=AUTH, files={"image": ("image.npy", _npy(small)), "mask": ("mask.npy", _npy(mask))})
    assert lama.status_code == 200, lama.text
    assert np.load(io.BytesIO(lama.content)).shape == (256, 256, 3)
    L = cv2.cvtColor(cv2.resize(small, (256, 256)).astype(np.float32) / 255, cv2.COLOR_BGR2LAB)[..., 0]
    ab = client.post("/v1/colorize", headers=AUTH, files={"image": ("image.npy", _npy(L))})
    assert np.load(io.BytesIO(ab.content)).shape == (256, 256, 2)
    d = client.post("/v1/depth", headers=AUTH, files={"image": ("image.npy", _npy(img))})
    assert np.load(io.BytesIO(d.content)).shape == (h, w)
