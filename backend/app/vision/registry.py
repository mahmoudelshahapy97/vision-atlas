"""The Vision Lab's models, served by models-serve (MODELS_URL).

The models run in their own service (vision-atlas/models-serve) so they can
sit on a GPU host; the pipelines stay here. `manager` keeps the interface the
pipelines always used: `use()`/`get()` hand back proxies with the methods they
call (`predict`, `track`, `embed`, `readtext`, LaTeX `model(image)`, …) and
predictions come back as numpy-backed look-alikes of Ultralytics Results.

YuNet and SFace are tiny OpenCV models called once per face, so only their
files come from models-serve; they run here.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from ..core.config import config

log = logging.getLogger("atlas.models")

ULTRA_TASKS = {"detect", "segment", "classify", "pose", "obb"}
LOCAL_FILE_MODELS = {"yunet", "sface"}
# Ultralytics arguments that only matter in-process; models-serve sets its own.
_LOCAL_KW = {"verbose", "device", "persist", "stream", "save"}


class ModelError(RuntimeError):
    """Raised with a message that can be shown to the user."""


class _CustomMissing(Exception):
    pass


# ---------------------------------------------------------------- wire format (see models-serve/app/codec.py)

def _jpg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise ModelError("Couldn't encode the image for the model server.")
    return buf.tobytes()


def _npy(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(arr), allow_pickle=False)
    return buf.getvalue()


def _image_part(img: np.ndarray, exact: bool = False) -> tuple[str, bytes]:
    return ("image.npy", _npy(img)) if exact else ("image.jpg", _jpg(img))


class _T:
    """Stands in for a torch tensor: `.cpu().numpy()`, len, indexing, float()."""

    def __init__(self, a):
        self._a = np.asarray(a)

    def cpu(self):
        return self

    def numpy(self) -> np.ndarray:
        return self._a

    def tolist(self):
        return self._a.tolist()

    def __len__(self) -> int:
        return len(self._a)

    def __getitem__(self, i):
        return _T(self._a[i])

    def __float__(self) -> float:
        return float(self._a)

    def __int__(self) -> int:
        return int(self._a)

    def __array__(self, dtype=None, copy=None):
        return self._a if dtype is None else self._a.astype(dtype)


def _shaped(v, tail: tuple[int, ...], dtype=np.float32) -> np.ndarray:
    a = np.asarray(v if v is not None else [], dtype=dtype)
    return a.reshape((-1, *tail)) if tail else a


class _Boxes:
    def __init__(self, d: dict, obb: bool = False):
        if obb:
            self.xyxyxyxy = _T(_shaped(d["xyxyxyxy"], (4, 2)))
            self.xywhr = _T(_shaped(d["xywhr"], (5,)))
        else:
            self.xyxy = _T(_shaped(d["xyxy"], (4,)))
        self.cls = _T(_shaped(d["cls"], ()))
        self.conf = _T(_shaped(d["conf"], ()))
        self.id = _T(_shaped(d["id"], ())) if d.get("id") is not None else None

    def __len__(self) -> int:
        return len(self.cls)


class _Masks:
    def __init__(self, d: dict):
        self.xy = [np.asarray(p, dtype=np.float32).reshape(-1, 2) for p in d["xy"]]
        self.data = None
        if d.get("data"):
            shape = d["data"]["shape"]
            bits = np.unpackbits(np.frombuffer(base64.b64decode(d["data"]["bits"]), np.uint8))
            self.data = _T(bits[: int(np.prod(shape))].reshape(shape).astype(np.float32))

    def __len__(self) -> int:
        return len(self.xy)


class _Keypoints:
    def __init__(self, d: dict):
        xy = np.asarray(d["xy"], dtype=np.float32)
        self.xy = _T(xy.reshape(0, 0, 2) if xy.size == 0 else xy)
        self.conf = _T(np.asarray(d["conf"], dtype=np.float32)) if d.get("conf") is not None else None

    def __len__(self) -> int:
        return len(self.xy)


class _Probs:
    def __init__(self, d: dict):
        self.data = _T(np.asarray(d["data"], dtype=np.float32))
        a = self.data.numpy()
        self.top1 = int(a.argmax())
        self.top1conf = _T(a[self.top1])
        self.top5 = [int(i) for i in np.argsort(-a)[:5]]
        self.top5conf = _T(a[self.top5])


class RemoteResult:
    """The parts of ultralytics.engine.results.Results the pipelines read."""

    def __init__(self, d: dict):
        self.names = {int(k): v for k, v in d["names"].items()}
        self.orig_shape = tuple(d.get("orig_shape") or ())
        self.boxes = _Boxes(d["boxes"]) if d.get("boxes") is not None else None
        self.masks = _Masks(d["masks"]) if d.get("masks") is not None else None
        self.keypoints = _Keypoints(d["keypoints"]) if d.get("keypoints") is not None else None
        self.probs = _Probs(d["probs"]) if d.get("probs") is not None else None
        self.obb = _Boxes(d["obb"], obb=True) if d.get("obb") is not None else None


# ---------------------------------------------------------------- HTTP

class _Client:
    def __init__(self) -> None:
        self._http: httpx.Client | None = None
        self._guard = threading.Lock()

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            with self._guard:
                if self._http is None:
                    headers = {"Authorization": f"Bearer {config.models_token}"} if config.models_token else {}
                    self._http = httpx.Client(base_url=config.models_url.rstrip("/"), headers=headers,
                                              timeout=httpx.Timeout(config.models_timeout, connect=5.0),
                                              limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
        return self._http

    def request(self, method: str, path: str, meta: dict | None = None, files: list | None = None,
                timeout: float | None = None, **kw) -> httpx.Response:
        if meta is not None:
            kw["data"] = {"meta": json.dumps(meta)}
        if files is not None:
            kw["files"] = files
        if timeout is not None:
            kw["timeout"] = timeout
        try:
            r = self.http.request(method, path, **kw)
        except httpx.TransportError as e:
            raise ModelError(f"Model server unreachable at {config.models_url} ({type(e).__name__}).") from e
        if r.is_success:
            return r
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:300]}
        detail = body.get("detail") if isinstance(body, dict) else body
        detail = detail if isinstance(detail, str) else json.dumps(detail)[:300]
        if r.status_code == 409 and isinstance(body, dict) and body.get("error") == "custom_missing":
            raise _CustomMissing(detail)
        if r.status_code in (400, 404, 422, 503):
            raise ModelError(detail or f"Model server answered {r.status_code}.")
        if r.status_code == 401:
            raise ModelError("The model server rejected MODELS_TOKEN.")
        raise RuntimeError(detail or f"Model server answered {r.status_code}.")


# ---------------------------------------------------------------- model proxies

def _sources(source) -> tuple[list[np.ndarray], bool]:
    if isinstance(source, (str, Path)):
        img = cv2.imread(str(source))
        if img is None:
            raise ModelError(f"Couldn't read {source}.")
        return [img], False
    if isinstance(source, (list, tuple)):
        return [np.asarray(s) for s in source], True
    return [np.asarray(source)], False


class RemoteModel:
    """One model on models-serve. Only the methods that make sense for the
    model's kind are ever called by the pipelines."""

    def __init__(self, manager: "ModelManager", key: str, args: tuple = ()):
        self._m, self.key, self.args = manager, key, args

    def _call(self, path: str, meta: dict, files: list) -> httpx.Response:
        return self._m._infer(path, {"model": self.key, **meta}, files)

    # Ultralytics
    def predict(self, source, **kw) -> list[RemoteResult]:
        imgs, batch = _sources(source)
        kw = {k: v for k, v in kw.items() if k not in _LOCAL_KW}
        meta = {"kwargs": kw, "batch": batch, "mask_data": self.key == "sam2"}
        r = self._call("/v1/predict", meta, [("image", _image_part(i)) for i in imgs])
        return [RemoteResult(d) for d in r.json()["results"]]

    def yoloe(self, prompts: list[str], source, **kw) -> list[RemoteResult]:
        """YOLOE-26 open-vocabulary prediction; models-serve caches the prompt set."""
        imgs, batch = _sources(source)
        kw = {k: v for k, v in kw.items() if k not in _LOCAL_KW}
        r = self._call("/v1/yoloe", {"prompts": prompts, "kwargs": kw, "batch": batch}, [("image", _image_part(i)) for i in imgs])
        return [RemoteResult(d) for d in r.json()["results"]]

    def embed(self, source, **kw) -> list[_T]:
        imgs, _ = _sources(source)
        r = self._call("/v1/embed", {}, [("image", _image_part(i)) for i in imgs])
        return [_T(row) for row in np.load(io.BytesIO(r.content), allow_pickle=False)]

    # EasyOCR
    def readtext(self, img: np.ndarray, **kw) -> list:
        meta = {"langs": list(self.args[0]) if self.args else ["en"], "kwargs": kw}
        items = self._m._client.request("POST", "/v1/ocr", meta, [("image", _image_part(img))]).json()["items"]
        return [tuple(it) for it in items]

    # LaTeX-OCR: model(PIL image) -> str
    def __call__(self, image) -> str:
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        return self._m._client.request("POST", "/v1/latex", files=[("image", _image_part(bgr, exact=True))]).json()["latex"]

    # torch networks: numpy in, numpy out
    def _array(self, path: str, **parts: np.ndarray) -> np.ndarray:
        files = [(name, (f"{name}.npy", _npy(a))) for name, a in parts.items()]
        r = self._m._client.request("POST", path, files=files)
        return np.load(io.BytesIO(r.content), allow_pickle=False)

    def upscale(self, tile: np.ndarray) -> np.ndarray:
        """Real-ESRGAN: BGR uint8 tile -> 4x BGR uint8."""
        return self._array("/v1/realesrgan", image=tile)

    def inpaint(self, img: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """LaMa: BGR uint8 + mask, sides multiples of 8 -> BGR uint8."""
        return self._array("/v1/lama", image=img, mask=mask)

    def ab(self, L: np.ndarray) -> np.ndarray:
        """Colorization: 256x256 Lab lightness -> 256x256x2 ab."""
        return self._array("/v1/colorize", image=L.astype(np.float32))

    def depth(self, img: np.ndarray) -> np.ndarray:
        """MiDaS: BGR image -> relative inverse depth at the same size."""
        return self._array("/v1/depth", image=img)


def _end_session(client: _Client, sid: str) -> None:
    try:
        client.request("DELETE", f"/v1/track/{sid}", timeout=5.0)
    except Exception:  # the server's idle timeout cleans up anyway
        pass


class RemoteTracker(RemoteModel):
    """A tracking session on models-serve: its own model instance, kept between frames."""

    def __init__(self, manager: "ModelManager", key: str):
        super().__init__(manager, key)
        self.session = uuid.uuid4().hex
        weakref.finalize(self, _end_session, manager._client, self.session)

    def track(self, source, tracker: str = "bytetrack.yaml", **kw) -> list[RemoteResult]:
        img = _sources(source)[0][0]
        kw = {k: v for k, v in kw.items() if k not in _LOCAL_KW}
        meta = {"session": self.session, "tracker": tracker, "kwargs": kw}
        r = self._call("/v1/track", meta, [("image", _image_part(img))])
        return [RemoteResult(d) for d in r.json()["results"]]


# ---------------------------------------------------------------- manager

class ModelManager:
    def __init__(self) -> None:
        self._client = _Client()
        self._guard = threading.Lock()
        self._ready: set[str] = set()       # keys models-serve has confirmed it can load
        self._catalog: dict[str, dict] = {}
        self._catalog_tried = 0.0
        # "custom:<id>" -> weights path, filled by the API when it accepts a run
        # that uses an uploaded model (the engine never reads the database).
        self._custom_paths: dict[str, str] = {}
        self._custom_sha: dict[str, tuple[float, str]] = {}

    # ---------- uploaded models ----------
    def register_custom(self, key: str, path: str) -> None:
        with self._guard:
            self._custom_paths[key] = path

    def forget_custom(self, key: str) -> None:
        with self._guard:
            self._custom_paths.pop(key, None)
            sha = self._custom_sha.pop(key, (0, ""))[1]
        try:
            self._client.request("DELETE", f"/v1/custom/{key}", headers={"X-Content-SHA256": sha}, timeout=10.0)
        except (ModelError, RuntimeError) as e:
            log.warning("Couldn't remove %s from the model server: %s", key, e)

    def _custom_path(self, key: str) -> Path:
        path = self._custom_paths.get(key)
        if not path or not Path(path).exists():
            raise ModelError("That uploaded model no longer exists.")
        return Path(path)

    def _sha(self, key: str) -> str:
        p = self._custom_path(key)
        mtime = p.stat().st_mtime
        cached = self._custom_sha.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        self._custom_sha[key] = (mtime, h.hexdigest())
        return h.hexdigest()

    def _push(self, key: str) -> None:
        sha = self._sha(key)
        log.info("Pushing %s to the model server", key)
        with open(self._custom_path(key), "rb") as f:
            self._client.request("PUT", f"/v1/custom/{key}", content=f, headers={"X-Content-SHA256": sha})

    def _infer(self, path: str, meta: dict, files: list) -> httpx.Response:
        """POST an inference request; push an uploaded model first if the server lacks it."""
        key = meta["model"]
        if key.startswith("custom:"):
            meta["custom_sha"] = self._sha(key)
        try:
            return self._client.request("POST", path, meta, files)
        except _CustomMissing:
            self._push(key)
            return self._client.request("POST", path, meta, files)

    # ---------- loading ----------
    @contextmanager
    def use(self, key: str, *args):
        """Kept for the pipelines' `with manager.use(key) as m:`. Locking happens on models-serve."""
        yield self.get(key, *args)

    def get(self, key: str, *args) -> Any:
        """A proxy for the model, after models-serve confirmed it can load it
        (so a missing optional model fails here, where pipelines expect it)."""
        if key in LOCAL_FILE_MODELS:
            return str(self.fetch_file(key, config.weights_dir / "served"))
        if key.startswith("custom:"):
            self._custom_path(key)
        elif key not in self._ready:
            self.load(key)
        return RemoteModel(self, key, args)

    def fresh(self, key: str) -> RemoteTracker:
        """A tracking session (Ultralytics tracking keeps per-video state in the model)."""
        if key.startswith("custom:"):
            self._custom_path(key)
        return RemoteTracker(self, key)

    def load(self, key: str) -> None:
        """Download (if needed) and load on models-serve."""
        self._client.request("POST", f"/v1/models/{key}/load")
        with self._guard:
            self._ready.add(key)

    def fetch_file(self, key: str, folder: Path) -> Path:
        """Copy a model's weights file from models-serve into `folder` (once)."""
        name = (self.specs().get(key) or {}).get("file") or f"{key}.onnx"
        dest = folder / name
        if dest.exists():
            return dest
        folder.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + f".{uuid.uuid4().hex[:8]}.part")
        try:
            with self._client.http.stream("GET", f"/v1/models/{key}/file") as r:
                if not r.is_success:
                    r.read()
                    raise ModelError(f"Couldn't get {key} from the model server: {r.text[:200]}")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
        except httpx.TransportError as e:
            raise ModelError(f"Model server unreachable at {config.models_url} ({type(e).__name__}).") from e
        finally:
            tmp.unlink(missing_ok=True)
        return dest

    # ---------- listing ----------
    def catalog(self) -> dict:
        """GET /v1/models: device, yolo_size and every public model with its status."""
        data = self._client.request("GET", "/v1/models", timeout=15.0).json()
        with self._guard:
            self._catalog = {m["key"]: m for m in data["models"]}
        return data

    def specs(self) -> dict[str, dict]:
        """Public model metadata (name, license, source, file …), cached after the first fetch."""
        if not self._catalog and time.monotonic() - self._catalog_tried > 30:
            self._catalog_tried = time.monotonic()
            try:
                self.catalog()
            except (ModelError, RuntimeError) as e:
                log.warning("Model catalog unavailable: %s", e)
        return self._catalog

    def inspect(self, path: Path) -> tuple[str, list[str]]:
        """(task, class names) of an uploaded Ultralytics checkpoint."""
        with open(path, "rb") as f:
            d = self._client.request("POST", "/v1/custom/inspect", files=[("file", (path.name, f))]).json()
        return d["task"], d["names"]

    def health(self) -> dict | None:
        try:
            return self._client.request("GET", "/health", timeout=3.0).json()
        except Exception:
            return None


manager = ModelManager()
