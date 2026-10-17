"""Everything that touches a model. Each function takes and returns numpy arrays
or plain data, so the routes only decode, call one of these and encode.

The enhancement maths (Real-ESRGAN, LaMa, colorization, MiDaS) moved here from
the API's pipelines/enhance.py; the pipelines keep the pre/post-processing.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .codec import InputError
from .core.config import config
from .registry import ModelError, _torch_device, manager, wdir

# Ultralytics arguments the pipelines use. Anything else (save=, project=, …)
# could make the server write files, so it is dropped.
PREDICT_KW = {"conf", "iou", "imgsz", "classes", "max_det", "points", "labels", "bboxes", "augment", "agnostic_nms"}
TRACKERS = {"bytetrack.yaml", "botsort.yaml"}
OCR_KW = {"detail", "paragraph", "allowlist", "blocklist", "decoder", "beamWidth", "batch_size", "text_threshold",
          "low_text", "link_threshold", "mag_ratio", "min_size", "width_ths", "height_ths", "x_ths", "y_ths",
          "rotation_info", "contrast_ths", "adjust_contrast"}


class CustomMissing(Exception):
    """The API must push the uploaded model's file first (409)."""


def predict_kwargs(kw: dict | None) -> dict:
    out = {k: v for k, v in (kw or {}).items() if k in PREDICT_KW}
    out.update(verbose=False, device=config.device)
    return out


# ------------------------------------------------------------------ uploaded models

_SHA = re.compile(r"^[0-9a-f]{64}$")
_custom_sha: dict[str, str] = {}
_custom_guard = threading.Lock()


def custom_file(sha: str) -> Path:
    if not _SHA.match(sha or ""):
        raise InputError("custom_sha must be a lowercase hex sha256.")
    folder = wdir() / "custom"
    folder.mkdir(exist_ok=True)
    return folder / f"{sha}.pt"


def ensure_custom(key: str, sha: str | None) -> None:
    """Point `custom:<id>` at the pushed file with this sha256 (it is kept across restarts)."""
    if not key.startswith("custom:"):
        return
    if not sha:
        raise InputError("custom_sha is required for uploaded models.")
    with _custom_guard:
        if _custom_sha.get(key) == sha:
            return
        path = custom_file(sha)
        if not path.exists():
            raise CustomMissing(f"{key} ({sha[:12]}) is not on the model server yet.")
        manager.forget_custom(key)
        manager.register_custom(key, str(path))
        _custom_sha[key] = sha


def forget_custom(key: str) -> None:
    with _custom_guard:
        _custom_sha.pop(key, None)
        manager.forget_custom(key)


def inspect_weights(path: Path) -> tuple[str, list[str]]:
    """(task, class names) of an Ultralytics checkpoint; raises if it won't load."""
    from ultralytics import YOLO

    m = YOLO(str(path))
    return m.task, [m.names[i] for i in sorted(m.names)]


# ------------------------------------------------------------------ Ultralytics

def predict(key: str, source: Any, kw: dict | None):
    with manager.use(key) as m:
        return m.predict(source, **predict_kwargs(kw))


def yoloe(prompts: list[str], source: Any, kw: dict | None):
    prompts = [p.strip() for p in prompts if isinstance(p, str) and p.strip()]
    if not prompts:
        raise InputError("Add at least one thing to look for.")
    with manager.use("yoloe26") as m:
        if getattr(m, "_atlas_prompts", None) != prompts:
            m.set_classes(prompts)
            m._atlas_prompts = prompts
        return m.predict(source, **predict_kwargs(kw))


def embed(key: str, imgs: list[np.ndarray]) -> np.ndarray:
    with manager.use(key) as m:
        return np.stack([e.cpu().numpy().ravel() for e in m.embed(imgs, verbose=False)]).astype(np.float32)


# ------------------------------------------------------------------ OCR

def _plain(v):
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def ocr(langs: list[str], img: np.ndarray, kw: dict | None) -> list:
    langs = tuple(langs) or ("en",)
    with manager.use("easyocr", langs) as r:
        items = r.readtext(img, **{k: v for k, v in (kw or {}).items() if k in OCR_KW})
    return _plain(items)


def latex(img: np.ndarray) -> str:
    from PIL import Image

    with manager.use("latex-ocr") as model:
        return model(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))


# ------------------------------------------------------------------ enhancement (torch)

def realesrgan(tile: np.ndarray) -> np.ndarray:
    """BGR uint8 tile -> BGR uint8 tile at 4x."""
    import torch

    with manager.use("realesrgan") as net:
        dev = next(net.parameters()).device
        x = torch.from_numpy(cv2.cvtColor(tile, cv2.COLOR_BGR2RGB).transpose(2, 0, 1).copy()).float().div(255).unsqueeze(0)
        with torch.no_grad():
            o = net(x.to(dev)).cpu()
    res = o.squeeze(0).clamp(0, 1).mul(255).byte().numpy().transpose(1, 2, 0)
    return cv2.cvtColor(res, cv2.COLOR_RGB2BGR)


def lama(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """BGR uint8 image and mask (>0 = fill), both padded to a multiple of 8 -> BGR uint8."""
    import torch

    if img.shape[0] % 8 or img.shape[1] % 8 or mask.shape[:2] != img.shape[:2]:
        raise InputError("LaMa needs an image and a mask of the same size, both multiples of 8.")
    with manager.use("lama") as net:
        dev = _torch_device()
        t_img = torch.from_numpy(cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1).copy()).float().div(255).unsqueeze(0).to(dev)
        t_mask = torch.from_numpy((mask > 0).astype(np.float32))[None, None].to(dev)
        with torch.no_grad():
            res = net(t_img, t_mask)[0].permute(1, 2, 0).clamp(0, 1).mul(255).byte().cpu().numpy()
    return cv2.cvtColor(res, cv2.COLOR_RGB2BGR)


def colorize(L: np.ndarray) -> np.ndarray:
    """Lab lightness (256x256 float32, 0..100) -> predicted ab channels (256x256x2 float32)."""
    import torch

    with manager.use("colorization") as net:
        with torch.no_grad():
            return net(torch.from_numpy(L.astype(np.float32))[None, None]).squeeze(0).numpy().transpose(1, 2, 0)


def depth(img: np.ndarray) -> np.ndarray:
    """BGR image -> relative inverse depth (bigger = closer), same size, float32."""
    import torch

    with manager.use("midas") as (net, transform):
        dev = next(net.parameters()).device
        x = transform(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).to(dev)
        with torch.no_grad():
            pred = net(x)
            pred = torch.nn.functional.interpolate(pred.unsqueeze(1), size=img.shape[:2], mode="bicubic", align_corners=False).squeeze()
    return pred.cpu().numpy().astype(np.float32)


def check_key(key: str) -> None:
    from .registry import SPECS

    if not key.startswith("custom:") and key not in SPECS:
        raise ModelError(f"Unknown model '{key}'.")
