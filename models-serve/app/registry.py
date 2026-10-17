"""Public and uploaded models: where they come from, how they load, and a thread-safe cache.

Every built-in model downloads on first use into WEIGHTS_DIR (or ahead of time with
`python -m app.download`). Loaded models are cached; each has a lock so two runs
never share a model's internal state at the same time.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .core.config import config

log = logging.getLogger("atlas.models")
S = config.yolo_size


@dataclass
class ModelSpec:
    key: str
    name: str
    kind: str                # ultralytics | yoloe | sam | url | hf | easyocr | midas | latex | colorization
    task: str                # what it does, shown in the UI
    license: str
    source: str              # where the weights come from (shown to users)
    file: str | None = None  # file name inside WEIGHTS_DIR
    url: str | None = None
    repo: str | None = None  # Hugging Face repo id
    classes: str = ""
    size_mb: float = 0
    note: str = ""
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("extra")
        return d


GH_ASSETS = "https://github.com/ultralytics/assets/releases/download/v8.4.0"
ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"

SPECS: dict[str, ModelSpec] = {s.key: s for s in [
    ModelSpec("yolo26-detect", f"YOLO26{S} detect", "ultralytics", "Object detection", "AGPL-3.0",
              "Ultralytics (official)", file=f"yolo26{S}.pt", url=f"{GH_ASSETS}/yolo26{S}.pt",
              classes="80 COCO classes (person, car, bus, bottle, dog …)", size_mb=5.3),
    ModelSpec("yolo26-segment", f"YOLO26{S} segment", "ultralytics", "Instance segmentation", "AGPL-3.0",
              "Ultralytics (official)", file=f"yolo26{S}-seg.pt", url=f"{GH_ASSETS}/yolo26{S}-seg.pt",
              classes="80 COCO classes", size_mb=6.4),
    ModelSpec("yolo26-pose", f"YOLO26{S} pose", "ultralytics", "Human pose (17 keypoints)", "AGPL-3.0",
              "Ultralytics (official)", file=f"yolo26{S}-pose.pt", url=f"{GH_ASSETS}/yolo26{S}-pose.pt",
              classes="person, 17 COCO keypoints", size_mb=7.5),
    ModelSpec("yolo26-classify", f"YOLO26{S} classify", "ultralytics", "Image classification", "AGPL-3.0",
              "Ultralytics (official)", file=f"yolo26{S}-cls.pt", url=f"{GH_ASSETS}/yolo26{S}-cls.pt",
              classes="1000 ImageNet classes", size_mb=5.5),
    ModelSpec("yolo26-obb", f"YOLO26{S} OBB", "ultralytics", "Oriented boxes for aerial images", "AGPL-3.0",
              "Ultralytics (official)", file=f"yolo26{S}-obb.pt", url=f"{GH_ASSETS}/yolo26{S}-obb.pt",
              classes="15 DOTA classes (plane, ship, vehicles, storage tank …)", size_mb=5.6),
    ModelSpec("yoloe26", f"YOLOE-26{S} open vocabulary", "yoloe", "Detect + segment anything you name", "AGPL-3.0",
              "Ultralytics (official)", file=f"yoloe-26{S}-seg.pt", url=f"{GH_ASSETS}/yoloe-26{S}-seg.pt",
              classes="Any text prompt, e.g. 'helmet, safety vest'", size_mb=11.7 if S == "n" else 31,
              extra={"text_model": "mobileclip2_b.ts"}),
    ModelSpec("sam2", "SAM 2.1 tiny", "sam", "Promptable segmentation (points/boxes)", "Apache-2.0",
              "Meta, via Ultralytics", file="sam2.1_t.pt", url=f"{GH_ASSETS}/sam2.1_t.pt", size_mb=78),
    ModelSpec("plate-yolo26", "YOLO26n license plates", "hf", "License plate detection", "AGPL-3.0",
              "Hugging Face · ishaqinu/yolo26n-license-plate-detection", file="alpr_26n.pt",
              repo="ishaqinu/yolo26n-license-plate-detection", classes="License_Plate", size_mb=5.4,
              note="Community model fine-tuned from yolo26n (mAP50 0.96). Falls back to YOLOE-26 prompts if it can't be downloaded."),
    ModelSpec("ppe-yolov8", "YOLOv8m PPE (14 classes)", "hf", "Safety equipment detection", "CC-BY-4.0",
              "Hugging Face · Hexmon/vyra-yolo-ppe-detection", file="ppe_yolov8m.pt",
              repo="Hexmon/vyra-yolo-ppe-detection", extra={"remote_file": "best.pt"},
              classes="Hardhat, NO-Hardhat, Safety Vest, NO-Safety Vest, Mask, Gloves, Person …", size_mb=52,
              note="Community model. Falls back to YOLOE-26 prompts if it can't be downloaded."),
    ModelSpec("easyocr", "EasyOCR (Arabic + English)", "easyocr", "Text detection and recognition", "Apache-2.0",
              "JaidedAI/EasyOCR (GitHub releases)", file="easyocr", size_mb=100),
    ModelSpec("latex-ocr", "LaTeX-OCR (pix2tex)", "latex", "Math formula to LaTeX", "MIT",
              "lukas-blecher/LaTeX-OCR (GitHub releases)", size_mb=100,
              note="Best on printed formulas; neat handwriting works partly."),
    ModelSpec("yunet", "YuNet face detector", "url", "Face detection + 5 landmarks", "MIT",
              "OpenCV Zoo", file="face_detection_yunet_2023mar.onnx",
              url=f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx", size_mb=0.2),
    ModelSpec("sface", "SFace face recognizer", "url", "Face embeddings for verification", "Apache-2.0",
              "OpenCV Zoo", file="face_recognition_sface_2021dec.onnx",
              url=f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx", size_mb=37),
    ModelSpec("realesrgan", "Real-ESRGAN general x4", "url", "4× super-resolution", "BSD-3-Clause",
              "xinntao/Real-ESRGAN (GitHub releases)", file="realesr-general-x4v3.pth",
              url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth", size_mb=4.7),
    ModelSpec("lama", "Big-LaMa inpainting", "url", "Fill removed regions realistically", "Apache-2.0",
              "advimman/lama, TorchScript by Sanster", file="big-lama.pt",
              url="https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt", size_mb=196),
    ModelSpec("midas", "MiDaS v2.1 small", "midas", "Relative depth from one image", "MIT",
              "isl-org/MiDaS (GitHub)", size_mb=82),
    ModelSpec("colorization", "Colorful Image Colorization (ECCV16)", "colorization", "Grayscale to color", "BSD-2-Clause",
              "richzhang/colorization", file="colorization_release_v2-9b330a0b.pth",
              url="https://colorizers.s3.us-east-2.amazonaws.com/colorization_release_v2-9b330a0b.pth", size_mb=123),
]}

ULTRA_TASKS = {"detect", "segment", "classify", "pose", "obb"}


class ModelError(RuntimeError):
    """Raised with a message that can be shown to the user."""


def wdir() -> Path:
    config.weights_dir.mkdir(parents=True, exist_ok=True)
    return config.weights_dir


def _download(url: str, dest: Path) -> Path:
    if not config.allow_model_downloads:
        raise ModelError(f"{dest.name} is not on disk and model downloads are turned off (ALLOW_MODEL_DOWNLOADS=false).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("Downloading %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vision-atlas/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1 << 20)
        if tmp.stat().st_size < 10_000:
            raise ModelError(f"Download of {dest.name} returned an unexpectedly small file.")
        tmp.replace(dest)
    except ModelError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:  # network errors, HTTP errors
        tmp.unlink(missing_ok=True)
        raise ModelError(f"Couldn't download {dest.name} from {url.split('/')[2]}: {e}") from e
    return dest


class ModelManager:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()
        # "custom:<id>" -> weights path, filled by the API when it accepts a run
        # that uses an uploaded model (the engine never reads the database).
        self._custom_paths: dict[str, str] = {}

    # ---------- uploaded models ----------
    def register_custom(self, key: str, path: str) -> None:
        with self._guard:
            self._custom_paths[key] = path

    def forget_custom(self, key: str) -> None:
        with self._guard:
            self._custom_paths.pop(key, None)
            for k in [k for k in self._cache if k == key or k.startswith(key + ":")]:
                del self._cache[k]

    # ---------- locking ----------
    def lock(self, key: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    @contextmanager
    def use(self, key: str, *args):
        """Load (if needed) and hold the model's lock while the caller uses it."""
        with self.lock(key):
            yield self.get(key, *args)

    # ---------- files ----------
    def is_downloaded(self, key: str) -> bool:
        spec = SPECS[key]
        if spec.kind == "easyocr":
            d = wdir() / "easyocr"
            return (d / "craft_mlt_25k.pth").exists() and (d / "arabic.pth").exists()
        if spec.kind == "midas":
            return (wdir() / "torchhub" / "checkpoints" / "midas_v21_small_256.pt").exists()
        if spec.kind == "latex":
            try:
                import pix2tex  # noqa: F401
                ck = Path(pix2tex.__file__).parent / "model" / "checkpoints" / "weights.pth"
                return ck.exists()
            except ImportError:
                return False
        if spec.kind == "yoloe":
            return (wdir() / spec.file).exists() and (wdir() / spec.extra["text_model"]).exists()
        return bool(spec.file) and (wdir() / spec.file).exists()

    def fetch(self, key: str) -> Path | None:
        """Make sure the model's files are on disk."""
        spec = SPECS.get(key)
        if spec is None:
            raise ModelError(f"Unknown model '{key}'.")
        if spec.kind in ("ultralytics", "sam", "url", "colorization"):
            p = wdir() / spec.file
            return p if p.exists() else _download(spec.url, p)
        if spec.kind == "yoloe":
            for f in (spec.file, spec.extra["text_model"]):
                if not (wdir() / f).exists():
                    _download(f"{GH_ASSETS}/{f}", wdir() / f)
            return wdir() / spec.file
        if spec.kind == "hf":
            p = wdir() / spec.file
            if p.exists():
                return p
            remote = spec.extra.get("remote_file", spec.file)
            return _download(f"https://huggingface.co/{spec.repo}/resolve/main/{remote}", p)
        if spec.kind == "midas":
            self._midas_sources()
            return None
        return None  # easyocr / latex download through their own libraries on first load

    def _midas_sources(self) -> Path:
        hub = wdir() / "hub"
        hub.mkdir(exist_ok=True)
        for repo, name in (("isl-org/MiDaS", "MiDaS"), ("rwightman/gen-efficientnet-pytorch", "gen-efficientnet-pytorch")):
            if not (hub / name).exists():
                if not config.allow_model_downloads:
                    raise ModelError("MiDaS sources are missing and downloads are turned off.")
                try:
                    subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{repo}", str(hub / name)],
                                   check=True, timeout=180, capture_output=True)
                except Exception as e:
                    raise ModelError(f"Couldn't fetch {repo} from GitHub: {e}") from e
        return hub

    # ---------- loading ----------
    def get(self, key: str, *args) -> Any:
        cache_key = key if not args else f"{key}:{args}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        with self.lock(f"load:{cache_key}"):
            if cache_key not in self._cache:
                self._cache[cache_key] = self._load(key, *args)
        return self._cache[cache_key]

    def fresh(self, key: str):
        """A new, uncached Ultralytics model instance (needed for tracking, which keeps per-video state)."""
        from ultralytics import YOLO
        if key.startswith("custom:"):
            return YOLO(self._custom_path(key))
        return YOLO(str(self.fetch(key)))

    def _custom_path(self, key: str) -> str:
        path = self._custom_paths.get(key)
        if not path or not Path(path).exists():
            raise ModelError("That uploaded model no longer exists.")
        return path

    def _load(self, key: str, *args) -> Any:
        _quiet_ultralytics()
        if key.startswith("custom:"):
            from ultralytics import YOLO
            return YOLO(self._custom_path(key))
        spec = SPECS.get(key)
        if spec is None:
            raise ModelError(f"Unknown model '{key}'.")
        kind = spec.kind
        if kind in ("ultralytics", "hf"):
            from ultralytics import YOLO
            return YOLO(str(self.fetch(key)))
        if kind == "yoloe":
            from ultralytics import YOLOE
            path = self.fetch(key)
            return YOLOE(str(path))
        if kind == "sam":
            from ultralytics import SAM
            return SAM(str(self.fetch(key)))
        if kind == "easyocr":
            import easyocr
            langs = list(args[0]) if args else ["en"]
            return easyocr.Reader(langs, gpu=config.device.startswith("cuda"), verbose=False,
                                  model_storage_directory=str(wdir() / "easyocr"),
                                  user_network_directory=str(wdir() / "easyocr"),
                                  download_enabled=config.allow_model_downloads)
        if kind == "url" and key == "realesrgan":
            import torch
            from .vendor.srvgg import SRVGGNetCompact
            net = SRVGGNetCompact()
            sd = torch.load(self.fetch(key), map_location="cpu", weights_only=True)
            net.load_state_dict(sd.get("params", sd))
            return net.eval().to(_torch_device())
        if kind == "url" and key == "lama":
            import torch
            return torch.jit.load(str(self.fetch(key)), map_location=_torch_device()).eval()
        if kind == "url":  # plain ONNX files used through OpenCV
            return str(self.fetch(key))
        if kind == "midas":
            return _load_midas(self._midas_sources())
        if kind == "latex":
            return _load_latex()
        if kind == "colorization":
            import torch
            from .vendor.eccv16 import ECCVGenerator
            net = ECCVGenerator()
            net.load_state_dict(torch.load(self.fetch(key), map_location="cpu", weights_only=True))
            return net.eval()
        raise ModelError(f"Don't know how to load '{key}'.")

    # ---------- listing ----------
    def status(self) -> list[dict]:
        out = []
        for key, spec in SPECS.items():
            d = spec.public()
            d["downloaded"] = self.is_downloaded(key)
            d["loaded"] = key in self._cache
            out.append(d)
        return out


def _torch_device() -> str:
    dev = config.device
    if dev.startswith("cuda"):
        import torch
        return dev if torch.cuda.is_available() else "cpu"
    return dev


def _quiet_ultralytics() -> None:
    os.environ.setdefault("YOLO_VERBOSE", "False")
    try:
        from ultralytics.utils import SETTINGS
        if SETTINGS.get("weights_dir") != str(wdir()):
            SETTINGS.update({"weights_dir": str(wdir()), "sync": False})
    except Exception:  # settings file not writable: harmless
        pass


def _load_midas(hub: Path):
    import torch
    local = {"rwightman/gen-efficientnet-pytorch": hub / "gen-efficientnet-pytorch",
             "isl-org/MiDaS": hub / "MiDaS", "intel-isl/MiDaS": hub / "MiDaS"}
    original = torch.hub.load

    def patched(repo, model, *a, **k):
        if repo in local:
            k.pop("trust_repo", None)
            k.pop("skip_validation", None)
            return original(str(local[repo]), model, *a, source="local", **k)
        return original(repo, model, *a, **k)

    torch.hub.set_dir(str(wdir() / "torchhub"))
    torch.hub.load = patched
    try:
        net = torch.hub.load("isl-org/MiDaS", "MiDaS_small").eval().to(_torch_device())
        transform = torch.hub.load("isl-org/MiDaS", "transforms").small_transform
    except Exception as e:
        raise ModelError(f"Couldn't load MiDaS: {e}") from e
    finally:
        torch.hub.load = original
    return net, transform


def _load_latex():
    try:
        import pix2tex.models.hybrid as hybrid
        # pix2tex was written for timm 0.5; newer timm passes extra kwargs to forward()
        hybrid.CustomVisionTransformer.forward = lambda self, x, **kw: self.forward_features(x)
        from pix2tex.cli import LatexOCR
    except ImportError as e:
        raise ModelError("LaTeX-OCR isn't installed. Install it with: pip install -r requirements-ml.txt") from e
    # In Docker the checkpoint files are symlinks into WEIGHTS_DIR/pix2tex (see the
    # Dockerfile), so they survive image rebuilds; pix2tex writes through them.
    (wdir() / "pix2tex").mkdir(exist_ok=True)
    return LatexOCR()


manager = ModelManager()
