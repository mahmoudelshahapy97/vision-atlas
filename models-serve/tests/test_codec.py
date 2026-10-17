import io

import cv2
import numpy as np
import pytest
import torch
from ultralytics.engine.results import Results

from app.codec import InputError, decode, npy, result_json

IMG = np.zeros((40, 60, 3), np.uint8)


def test_detection_and_masks_round_trip():
    boxes = torch.tensor([[1.0, 2.0, 11.0, 22.0, 7.0, 0.9, 0.0], [5.0, 5.0, 30.0, 35.0, 8.0, 0.5, 2.0]])  # with track ids
    masks = torch.zeros((2, 40, 60))
    masks[0, 2:22, 1:11] = 1
    masks[1, 5:35, 5:30] = 1
    r = Results(IMG, path="x.jpg", names={0: "person", 1: "bicycle", 2: "car"}, boxes=boxes, masks=masks)
    d = result_json(r, mask_data=True)
    assert d["names"] == {0: "person", 1: "bicycle", 2: "car"} and d["orig_shape"] == [40, 60]
    assert d["boxes"]["xyxy"][1] == [5, 5, 30, 35] and d["boxes"]["cls"] == [0, 2] and d["boxes"]["id"] == [7, 8]
    assert len(d["masks"]["xy"]) == 2 and d["masks"]["data"]["shape"] == [2, 40, 60]
    assert d["keypoints"] is None and d["probs"] is None and d["obb"] is None
    assert result_json(r)["masks"]["data"] is None


def test_probs_keypoints_obb():
    probs = Results(IMG, path="x", names={0: "a", 1: "b"}, probs=torch.tensor([0.25, 0.75]))
    assert result_json(probs)["probs"]["data"] == [0.25, 0.75]
    kp = Results(IMG, path="x", names={0: "person"}, boxes=torch.tensor([[0.0, 0.0, 9.0, 9.0, 0.8, 0.0]]),
                 keypoints=torch.rand(1, 17, 3))
    d = result_json(kp)
    assert np.asarray(d["keypoints"]["xy"]).shape == (1, 17, 2) and np.asarray(d["keypoints"]["conf"]).shape == (1, 17)
    obb = Results(IMG, path="x", names={0: "plane"}, obb=torch.tensor([[20.0, 20.0, 10.0, 6.0, 0.3, 0.7, 0.0]]))
    d = result_json(obb)
    assert np.asarray(d["obb"]["xyxyxyxy"]).shape == (1, 4, 2) and d["obb"]["cls"] == [0]


def test_decode_parts():
    a = np.arange(12, dtype=np.float32).reshape(3, 4)
    assert (decode(npy(a).body, "x.npy") == a).all()
    ok, png = cv2.imencode(".png", IMG)
    assert decode(png.tobytes(), "image.png").shape == (40, 60, 3)
    with pytest.raises(InputError):
        decode(b"nope", "image.jpg")
    buf = io.BytesIO()
    np.save(buf, np.array([{"x": 1}], dtype=object), allow_pickle=True)
    with pytest.raises(InputError):  # pickles are refused
        decode(buf.getvalue(), "evil.npy")
