"""Wire format between the API and models-serve.

Requests are multipart: a `meta` JSON field plus file parts. A part named
*.npy is a numpy array (np.save, no pickles); anything else is an encoded image
(JPEG/PNG) decoded with OpenCV, so colour images arrive as BGR like the
pipelines use them. Array answers go back as .npy, detection answers as JSON
that the API turns back into Result look-alikes (backend app/vision/registry.py).
"""
from __future__ import annotations

import base64
import io

import cv2
import numpy as np
from fastapi import Response

NPY = "application/x-npy"


class InputError(ValueError):
    """The request itself is wrong (400)."""


def decode(data: bytes, name: str | None) -> np.ndarray:
    if (name or "").endswith(".npy"):
        try:
            return np.load(io.BytesIO(data), allow_pickle=False)
        except Exception as e:
            raise InputError(f"Bad array part {name!r}: {e}") from e
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise InputError(f"Couldn't decode image part {name!r}.")
    return img


def npy(arr: np.ndarray) -> Response:
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(arr), allow_pickle=False)
    return Response(content=buf.getvalue(), media_type=NPY)


def _arr(t, decimals: int | None = None):
    if t is None:
        return None
    a = t.cpu().numpy() if hasattr(t, "cpu") else np.asarray(t)
    if decimals is not None and a.dtype.kind == "f":
        a = a.round(decimals)
    return a.tolist()


def result_json(r, mask_data: bool = False) -> dict:
    """One Ultralytics Results -> plain JSON with the fields the pipelines read."""
    out: dict = {"names": {int(k): v for k, v in r.names.items()}, "orig_shape": list(r.orig_shape),
                 "boxes": None, "masks": None, "keypoints": None, "probs": None, "obb": None}
    b = r.boxes
    if b is not None:
        out["boxes"] = {"xyxy": _arr(b.xyxy, 2), "cls": _arr(b.cls), "conf": _arr(b.conf, 5),
                        "id": _arr(b.id) if b.id is not None else None}
    m = r.masks
    if m is not None:
        out["masks"] = {"xy": [_arr(p, 1) for p in m.xy], "data": None}
        if mask_data:
            d = m.data.cpu().numpy() > 0.5
            out["masks"]["data"] = {"shape": list(d.shape), "bits": base64.b64encode(np.packbits(d).tobytes()).decode()}
    k = r.keypoints
    if k is not None:
        out["keypoints"] = {"xy": _arr(k.xy, 2), "conf": _arr(k.conf, 4) if k.conf is not None else None}
    p = r.probs
    if p is not None:
        out["probs"] = {"data": _arr(p.data, 6)}
    o = r.obb
    if o is not None:
        out["obb"] = {"xyxyxyxy": _arr(o.xyxyxyxy, 2), "xywhr": _arr(o.xywhr, 4), "cls": _arr(o.cls),
                      "conf": _arr(o.conf, 5), "id": _arr(o.id) if o.id is not None else None}
    return out
