"""The models-serve client (app/vision/registry.py) against a fake server: the
Result look-alikes must satisfy the helpers the pipelines use, and failures
must surface as ModelError. No database or model server needed."""
import base64
import gc
import io
import json

import httpx
import numpy as np
import pytest

from app.core.config import config
from app.vision.core import boxes_of, masks_of
from app.vision.pipelines.people import people_of
from app.vision.registry import ModelError, ModelManager, RemoteResult

IMG = np.zeros((48, 64, 3), np.uint8)
NAMES = {"0": "person", "1": "bicycle", "2": "car"}


def _result(**over):
    d = {"names": NAMES, "orig_shape": [48, 64], "boxes": None, "masks": None, "keypoints": None, "probs": None, "obb": None}
    d.update(over)
    return d


DET = _result(boxes={"xyxy": [[1, 2, 11, 22], [5, 5, 30, 40]], "cls": [0, 2], "conf": [0.9, 0.5], "id": [7, 8]},
              masks={"xy": [[[1, 2], [11, 2], [11, 22]], [[5, 5], [30, 5], [30, 40], [5, 40]]], "data": None})


def _npy(a) -> bytes:
    buf = io.BytesIO()
    np.save(buf, a)
    return buf.getvalue()


def _manager(handler) -> ModelManager:
    m = ModelManager()
    m._client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://models")
    return m


def _meta(request: httpx.Request) -> dict:
    body = request.read().decode("latin-1")
    start = body.index('name="meta"')
    chunk = body[start:].split("\r\n\r\n", 1)[1]
    return json.loads(chunk.split("\r\n--", 1)[0])


def test_detection_result_works_with_pipeline_helpers():
    def handler(req):
        if req.url.path.endswith("/load"):
            return httpx.Response(200, json={"loaded": True})
        assert req.url.path == "/v1/predict"
        meta = _meta(req)
        assert meta["model"] == "yolo26-segment" and meta["kwargs"] == {"conf": 0.3}  # device/verbose stripped
        return httpx.Response(200, json={"results": [DET]})

    m = _manager(handler)
    with m.use("yolo26-segment") as model:
        r = model.predict(IMG, conf=0.3, verbose=False, device="cuda:0")[0]
    dets = boxes_of(r)
    assert [d["cls"] for d in dets] == ["person", "car"] and dets[0]["id"] == 7 and dets[1]["box"] == [5, 5, 30, 40]
    masks = masks_of(r, IMG.shape)
    assert len(masks) == 2 and masks[1].shape == (48, 64) and masks[1].sum() > 0
    assert r.masks.xy[0].round(1).tolist()[0] == [1.0, 2.0]


def test_empty_and_other_result_kinds():
    empty = RemoteResult(_result(boxes={"xyxy": [], "cls": [], "conf": [], "id": None}))
    assert boxes_of(empty) == [] and masks_of(empty, IMG.shape) == []

    pose = RemoteResult(_result(boxes={"xyxy": [[0, 0, 10, 20]], "cls": [0], "conf": [0.8], "id": None},
                                keypoints={"xy": [[[1, 1]] * 17], "conf": [[0.9] * 16 + [0.1]]}))
    people = people_of(pose)
    assert len(people) == 1 and people[0]["ok"].sum() == 16 and people[0]["id"] is None
    assert people_of(RemoteResult(_result(boxes={"xyxy": [], "cls": [], "conf": [], "id": None},
                                          keypoints={"xy": [], "conf": None}))) == []

    cls = RemoteResult(_result(probs={"data": [0.1, 0.2, 0.7]}))
    assert cls.probs.top1 == 2 and abs(float(cls.probs.top1conf) - 0.7) < 1e-6
    assert cls.probs.data.cpu().numpy().shape == (3,) and cls.boxes is None

    obb = RemoteResult(_result(obb={"xyxyxyxy": [[[0, 0], [4, 0], [4, 4], [0, 4]]], "xywhr": [[2, 2, 4, 4, 0]],
                                    "cls": [1], "conf": [0.6], "id": None}))
    assert len(obb.obb) == 1 and obb.obb.xyxyxyxy.cpu().numpy().astype(np.int32).shape == (1, 4, 2)

    bits = np.zeros((1, 4, 4), bool)
    bits[0, 1:3, 1:3] = True
    sam = RemoteResult(_result(masks={"xy": [[[1, 1], [3, 1], [3, 3]]],
                                      "data": {"shape": [1, 4, 4], "bits": base64.b64encode(np.packbits(bits).tobytes()).decode()}}))
    assert ((sam.masks.data.cpu().numpy() > 0.5) == bits).all()


def test_uploaded_model_is_pushed_once_then_retried(tmp_path):
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"pretend weights")
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "PUT":
            assert req.read() == b"pretend weights" and len(req.headers["x-content-sha256"]) == 64
            return httpx.Response(200, json={})
        if sum(1 for c in calls if c == ("PUT", "/v1/custom/custom:5")) == 0:
            assert _meta(req)["custom_sha"]
            return httpx.Response(409, json={"detail": "not here", "error": "custom_missing"})
        return httpx.Response(200, json={"results": [DET]})

    m = _manager(handler)
    m.register_custom("custom:5", str(weights))
    assert len(boxes_of(m.get("custom:5").predict(IMG)[0])) == 2
    assert calls == [("POST", "/v1/predict"), ("PUT", "/v1/custom/custom:5"), ("POST", "/v1/predict")]
    m.get("custom:5").predict(IMG)
    assert calls[-1] == ("POST", "/v1/predict") and len(calls) == 4  # no second push

    weights.unlink()
    with pytest.raises(ModelError, match="no longer exists"):
        m.get("custom:5")


def test_errors_become_model_errors():
    def unreachable(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ModelError, match="unreachable"):
        _manager(unreachable).get("yolo26-detect")

    def server(req):
        if req.url.path.endswith("/load"):
            return httpx.Response(503, json={"detail": "Couldn't download alpr_26n.pt", "error": "model"})
        return httpx.Response(500, json={"detail": "CUDA out of memory", "error": "internal"})

    m = _manager(server)
    with pytest.raises(ModelError, match="alpr_26n"):  # the optional-model probe pipelines rely on
        m.get("plate-yolo26")
    m._ready.add("yolo26-detect")
    with pytest.raises(RuntimeError, match="out of memory"):
        m.get("yolo26-detect").predict(IMG)


def test_tracking_session_is_reused_and_closed():
    seen = []

    def handler(req):
        if req.method == "DELETE":
            seen.append(("end", req.url.path.rsplit("/", 1)[1]))
            return httpx.Response(204)
        meta = _meta(req)
        seen.append(("frame", meta["session"]))
        assert meta["tracker"] == "bytetrack.yaml" and "persist" not in meta["kwargs"]
        return httpx.Response(200, json={"results": [DET]})

    m = _manager(handler)
    t = m.fresh("yolo26-detect")
    for _ in range(2):
        assert boxes_of(t.track(IMG, persist=True, conf=0.25, tracker="bytetrack.yaml")[0])[0]["id"] == 7
    sid = t.session
    del t
    gc.collect()
    assert seen == [("frame", sid), ("frame", sid), ("end", sid)]


def test_array_models_and_ocr():
    def handler(req):
        p = req.url.path
        if p.endswith("/load"):
            return httpx.Response(200, json={})
        if p == "/v1/realesrgan":
            return httpx.Response(200, content=_npy(np.full((8, 8, 3), 9, np.uint8)))
        if p == "/v1/depth":
            return httpx.Response(200, content=_npy(np.ones((48, 64), np.float32)))
        if p == "/v1/ocr":
            assert _meta(req)["langs"] == ["ar", "en"]
            return httpx.Response(200, json={"items": [[[[0, 0], [5, 0], [5, 5], [0, 5]], "مرحبا", 0.9]]})
        raise AssertionError(p)

    m = _manager(handler)
    assert m.get("realesrgan").upscale(np.zeros((2, 2, 3), np.uint8)).shape == (8, 8, 3)
    assert m.get("midas").depth(IMG).shape == (48, 64)
    box, text, conf = m.get("easyocr", ("ar", "en")).readtext(IMG)[0]
    assert text == "مرحبا" and conf == 0.9 and len(box) == 4


def test_face_models_are_copied_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "weights_dir", tmp_path)
    hits = []

    def handler(req):
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"key": "yunet", "file": "face_detection_yunet_2023mar.onnx"}]})
        hits.append(req.url.path)
        return httpx.Response(200, content=b"onnx bytes")

    m = _manager(handler)
    first = m.get("yunet")
    assert first.endswith("served/face_detection_yunet_2023mar.onnx") and m.get("yunet") == first
    assert hits == ["/v1/models/yunet/file"]
