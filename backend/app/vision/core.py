"""Building blocks shared by every pipeline: inputs, outputs, models, video I/O, drawing."""
from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..core.config import config
from .registry import ModelError, manager

# ---------------------------------------------------------------- pipeline definition

INPUT_KINDS = {"image", "video", "media", "images"}


@dataclass
class Slot:
    name: str
    label: str
    kind: str = "image"      # image | video | media (image or video) | images (several)
    min: int = 1
    max: int = 1
    optional: bool = False

    def public(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Param:
    name: str
    label: str
    type: str = "number"     # number | int | text | textarea | select | multiselect | bool | line | polygon | polygons | points | box
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list | None = None
    help: str = ""
    advanced: bool = False

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Pipeline:
    name: str
    title: str
    description: str
    fn: Callable[["Ctx"], None]
    slots: list[Slot]
    params: list[Param] = field(default_factory=list)
    models: list[str] = field(default_factory=list)   # registry keys this pipeline may load
    custom_task: str | None = None                     # task of uploaded weights it accepts (detect/segment/classify/pose)

    def public(self) -> dict:
        return {
            "name": self.name, "title": self.title, "description": self.description,
            "slots": [s.public() for s in self.slots], "params": [p.public() for p in self.params],
            "models": self.models, "custom_task": self.custom_task,
        }


PIPELINES: dict[str, Pipeline] = {}


def pipeline(name: str, title: str, description: str, slots: list[Slot], params: list[Param] | None = None,
             models: list[str] | None = None, custom_task: str | None = None):
    def deco(fn):
        PIPELINES[name] = Pipeline(name, title, description, fn, slots, params or [], models or [], custom_task)
        return fn
    return deco


# shared parameter definitions
CONF = Param("conf", "Confidence threshold", "number", 0.25, 0.05, 0.95, 0.05,
             help="Lower finds more objects but more false alarms.")
STRIDE = Param("stride", "Process every Nth frame", "int", 1, 1, 10, 1, advanced=True,
               help="Higher is faster on long videos.")
IMGSZ = Param("imgsz", "Inference size (px)", "select", 640, options=[320, 480, 640, 960, 1280], advanced=True)
IMAGE = [Slot("image", "Image")]
MEDIA = [Slot("media", "Image or video", "media")]
VIDEO = [Slot("video", "Video", "video")]

COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
        "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
        "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
        "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
        "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
        "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
        "scissors", "teddy bear", "hair drier", "toothbrush"]
VEHICLES = ["car", "truck", "bus", "motorcycle", "bicycle"]


def resolve_params(pipe: Pipeline, project_params: dict | None, user_params: dict | None) -> dict:
    """Pipeline defaults, overridden by the project's lab defaults, overridden by what the user sent.
    Values are coerced to the declared type and clamped to min/max."""
    out = {p.name: p.default for p in pipe.params}
    for src in (project_params or {}, user_params or {}):
        for k, v in src.items():
            if v is not None:
                out[k] = v
    for p in pipe.params:
        v = out.get(p.name)
        try:
            if p.type in ("number", "int") and v is not None and v != "":
                v = float(v) if p.type == "number" else int(float(v))
                if p.min is not None:
                    v = max(p.min, v)
                if p.max is not None:
                    v = min(p.max, v)
            elif p.type == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif p.type == "select" and p.options and v not in p.options:
                # numbers arrive as strings from forms
                v = next((o for o in p.options if str(o) == str(v)), p.default)
            elif p.type == "multiselect" and isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
        except (TypeError, ValueError):
            raise UserError(f"'{p.label}' has an invalid value: {v!r}")
        out[p.name] = v
    if "model" in (user_params or {}):
        out["model"] = user_params["model"]
    return out


def classes_param(default: list[str] | None = None, label: str = "Classes to detect") -> Param:
    return Param("classes", label, "multiselect", default or [], options=COCO,
                 help="Leave empty to detect all 80 classes.")


# ---------------------------------------------------------------- inputs

@dataclass
class InputFile:
    slot: str
    path: Path
    name: str
    kind: str  # image | video

    def read(self) -> np.ndarray:
        img = read_image(self.path)
        if img is None:
            raise UserError(f"Couldn't read {self.name} as an image.")
        return img


class UserError(Exception):
    """An error caused by the input; the message is shown to the user as is."""


VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def read_image(path: Path, max_side: int = 4096) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


# ---------------------------------------------------------------- context

class Ctx:
    def __init__(self, run_id: str, inputs: list[InputFile], params: dict, out_dir: Path,
                 progress: Callable[[float], None] | None = None):
        self.run_id = run_id
        self.inputs = inputs
        self.params = params
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self._progress = progress or (lambda p: None)
        self.result: dict[str, Any] = {"summary": [], "images": [], "tables": [], "files": [], "notes": [],
                                       "text": None, "video": None, "chart": None, "data": {}, "speak": None}
        self._n = 0

    # ----- inputs
    def files(self, slot: str | None = None) -> list[InputFile]:
        return [f for f in self.inputs if slot is None or f.slot == slot]

    def file(self, slot: str | None = None) -> InputFile:
        fs = self.files(slot)
        if not fs:
            raise UserError(f"Add a file for '{slot}'." if slot else "Add a file to analyze.")
        return fs[0]

    def image(self, slot: str | None = None) -> np.ndarray:
        f = self.file(slot)
        if f.kind != "image":
            raise UserError(f"{f.name} is a video; this step needs an image.")
        return f.read()

    def images(self, slot: str | None = None) -> list[tuple[str, np.ndarray]]:
        out = []
        for f in self.files(slot):
            if f.kind == "image":
                img = read_image(f.path, 2048)
                if img is not None:
                    out.append((f.name, img))
        return out

    def p(self, name: str, default: Any = None) -> Any:
        v = self.params.get(name, default)
        return default if v is None or v == "" else v

    def progress(self, frac: float) -> None:
        self._progress(max(0.0, min(1.0, frac)))

    # ----- outputs
    def _url(self, path: Path) -> str:
        return "/media/" + path.relative_to(config.media_dir).as_posix()

    def _name(self, stem: str, ext: str) -> Path:
        self._n += 1
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem)[:40] or "out"
        return self.out_dir / f"{self._n:02d}-{safe}{ext}"

    def add_image(self, img: np.ndarray, caption: str = "", quality: int = 88) -> str:
        p = self._name(caption or "image", ".jpg")
        h, w = img.shape[:2]
        if max(h, w) > 2400:
            s = 2400 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise RuntimeError("Couldn't encode output image")
        p.write_bytes(buf.tobytes())
        url = self._url(p)
        self.result["images"].append({"url": url, "caption": caption, "width": int(img.shape[1]), "height": int(img.shape[0])})
        return url

    def add_png(self, img: np.ndarray, caption: str) -> str:
        p = self._name(caption, ".png")
        cv2.imwrite(str(p), img)
        url = self._url(p)
        self.result["images"].append({"url": url, "caption": caption, "width": int(img.shape[1]), "height": int(img.shape[0])})
        return url

    def stat(self, label: str, value: Any, tone: str | None = None, unit: str | None = None) -> None:
        if isinstance(value, float):
            value = round(value, 3 if abs(value) < 10 else 1)
        if isinstance(value, np.generic):
            value = value.item()
        self.result["summary"].append({"label": label, "value": value, **({"tone": tone} if tone else {}),
                                       **({"unit": unit} if unit else {})})

    def table(self, title: str, columns: list[str], rows: list[list[Any]], csv_name: str | None = None) -> None:
        clean = [[_jsonable(v) for v in r] for r in rows]
        self.result["tables"].append({"title": title, "columns": columns, "rows": clean[:500],
                                      "total_rows": len(clean)})
        if csv_name:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(columns)
            w.writerows(clean)
            self.add_file(buf.getvalue().encode("utf-8-sig"), csv_name)

    def add_file(self, data: bytes | Path, name: str) -> str:
        stem, ext = Path(name).stem, Path(name).suffix or ".bin"
        p = self._name(stem, ext)
        if isinstance(data, Path):
            data.replace(p)
        else:
            p.write_bytes(data)
        url = self._url(p)
        self.result["files"].append({"url": url, "name": name, "size": p.stat().st_size})
        return url

    def add_json(self, obj: Any, name: str) -> str:
        return self.add_file(json.dumps(obj, ensure_ascii=False, indent=2, default=_jsonable).encode(), name)

    def note(self, text: str) -> None:
        if text not in self.result["notes"]:
            self.result["notes"].append(text)

    def text(self, text: str, direction: str = "auto") -> None:
        self.result["text"] = {"content": text, "dir": direction}

    def chart(self, kind: str, title: str, x: list, series: list[dict], x_label: str = "", y_label: str = "") -> None:
        self.result["chart"] = {"type": kind, "title": title, "x": [_jsonable(v) for v in x],
                                "series": [{"name": s["name"], "values": [_jsonable(v) for v in s["values"]]} for s in series],
                                "x_label": x_label, "y_label": y_label}

    def data(self, **kw) -> None:
        self.result["data"].update({k: _jsonable(v) for k, v in kw.items()})

    # ----- models
    def model_key(self, default: str) -> str:
        """The built-in model, or an uploaded one the user picked in the form."""
        m = self.params.get("model")
        return m if isinstance(m, str) and m.startswith("custom:") else default

    def predict(self, key: str, source, **kw):
        """Ultralytics prediction on models-serve; Result look-alikes come back."""
        try:
            with manager.use(key) as m:
                return m.predict(source, **kw)
        except ModelError:
            raise
        except Exception as e:
            raise RuntimeError(f"{key} failed: {e}") from e

    def yoloe(self, prompts: list[str], source, **kw):
        """Open-vocabulary detection + segmentation with YOLOE-26."""
        prompts = [p.strip() for p in prompts if p and p.strip()]
        if not prompts:
            raise UserError("Add at least one thing to look for (comma-separated).")
        with manager.use("yoloe26") as m:
            return m.yoloe(prompts, source, **kw)

    def ocr(self, img: np.ndarray, langs: tuple[str, ...] = ("en",), **kw) -> list[tuple[list, str, float]]:
        langs = tuple(sorted(set(langs), key=lambda x: x != "en")) or ("en",)
        if "ar" in langs:  # EasyOCR's Arabic model reads Latin poorly, so run both and merge
            out = []
            with manager.use("easyocr", ("ar", "en")) as r:
                out += r.readtext(img, **kw)
            with manager.use("easyocr", ("en",)) as r:
                en = r.readtext(img, **kw)
            return merge_ocr(out, en)
        with manager.use("easyocr", langs) as r:
            return r.readtext(img, **kw)


def merge_ocr(primary, secondary):
    """Keep the higher-confidence reading where boxes from two OCR passes overlap."""
    result = list(primary)
    for box, text, conf in secondary:
        b = poly_bbox(box)
        clash = [i for i, (pb, _, _) in enumerate(result) if iou(b, poly_bbox(pb)) > 0.4]
        if not clash:
            result.append((box, text, conf))
        elif all(conf > result[i][2] for i in clash):
            for i in sorted(clash, reverse=True):
                result.pop(i)
            result.append((box, text, conf))
    return sorted(result, key=lambda r: (poly_bbox(r[0])[1] // 20, poly_bbox(r[0])[0]))


# ---------------------------------------------------------------- results helpers

def boxes_of(r) -> list[dict]:
    """Ultralytics result -> plain list of detections."""
    out = []
    if r.boxes is None:
        return out
    xyxy = r.boxes.xyxy.cpu().numpy()
    cls = r.boxes.cls.cpu().numpy().astype(int)
    conf = r.boxes.conf.cpu().numpy()
    ids = r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else [None] * len(cls)
    for i in range(len(cls)):
        x1, y1, x2, y2 = xyxy[i]
        out.append({"cls": r.names[cls[i]], "conf": float(conf[i]), "box": [float(x1), float(y1), float(x2), float(y2)],
                    "id": None if ids[i] is None else int(ids[i]), "i": i})
    return out


def masks_of(r, shape) -> list[np.ndarray]:
    """Binary masks at full image resolution, aligned with boxes_of()."""
    if r.masks is None:
        return []
    h, w = shape[:2]
    out = []
    for poly in r.masks.xy:
        m = np.zeros((h, w), np.uint8)
        if len(poly) >= 3:
            cv2.fillPoly(m, [poly.astype(np.int32)], 1)
        out.append(m)
    return out


def counts(dets: list[dict]) -> dict[str, int]:
    c: dict[str, int] = {}
    for d in dets:
        c[d["cls"]] = c.get(d["cls"], 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def det_rows(dets: list[dict]) -> list[list]:
    return [[d["cls"], round(d["conf"], 3), *[round(v) for v in d["box"]]] + ([d["id"]] if d.get("id") is not None else [])
            for d in dets]


DET_COLS = ["Class", "Confidence", "x1", "y1", "x2", "y2"]


def iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def poly_bbox(poly) -> list[float]:
    pts = np.asarray(poly, dtype=float).reshape(-1, 2)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]


def center(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _jsonable(v):
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (Path,)):
        return str(v)
    return v


# ---------------------------------------------------------------- geometry params (normalized 0..1 coordinates)

def norm_points(value, w: int, h: int) -> np.ndarray:
    pts = np.asarray(value or [], dtype=float).reshape(-1, 2)
    return (pts * [w, h]).astype(np.int32)


def polygons_param(value, w, h) -> list[np.ndarray]:
    if not value:
        return []
    if isinstance(value, list) and value and isinstance(value[0], list) and value[0] and isinstance(value[0][0], (int, float)):
        value = [value]  # a single polygon
    return [norm_points(p, w, h) for p in value if p and len(p) >= 3]


def point_in_poly(pt, poly: np.ndarray) -> bool:
    return cv2.pointPolygonTest(poly.astype(np.float32), (float(pt[0]), float(pt[1])), False) >= 0


def side_of_line(pt, a, b) -> float:
    return (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])


# ---------------------------------------------------------------- drawing

PALETTE = [(10, 151, 229), (214, 70, 36), (72, 133, 28), (180, 60, 200), (0, 110, 183), (60, 60, 200),
           (160, 140, 20), (40, 180, 160), (200, 100, 120), (90, 90, 90)]  # BGR; first = brand amber
AMBER, BLUE, GREEN, RED, WHITE, BLACK = (10, 151, 229), (214, 70, 36), (72, 133, 28), (60, 50, 220), (255, 255, 255), (20, 20, 20)


def color_for(name: str) -> tuple[int, int, int]:
    return PALETTE[sum(map(ord, name)) % len(PALETTE)]


def scale_for(img) -> float:
    return max(0.5, min(2.0, max(img.shape[:2]) / 900))


def label(img, text: str, x: int, y: int, color=AMBER, fg=BLACK) -> None:
    s = scale_for(img)
    fs, th = 0.5 * s, max(1, int(1.2 * s))
    (tw, tht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    y0 = max(tht + 6, y)
    cv2.rectangle(img, (x, y0 - tht - 6), (x + tw + 8, y0), color, -1)
    cv2.putText(img, text, (x + 4, y0 - 4), cv2.FONT_HERSHEY_SIMPLEX, fs, fg, th, cv2.LINE_AA)


def box(img, b, text: str | None = None, color=AMBER, thickness: int | None = None) -> None:
    s = scale_for(img)
    t = thickness or max(2, int(2 * s))
    x1, y1, x2, y2 = map(int, b)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, t)
    if text:
        label(img, text, x1, y1, color, BLACK if sum(color) > 380 else WHITE)


def overlay_mask(img, mask: np.ndarray, color, alpha: float = 0.45) -> None:
    m = mask.astype(bool)
    img[m] = (img[m] * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)


def banner(img, lines: list[str], color=(30, 30, 30)) -> np.ndarray:
    """Draw a translucent info panel in the top-left corner."""
    s = scale_for(img)
    fs, th = 0.55 * s, max(1, int(1.3 * s))
    sizes = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0] for t in lines]
    w = max((sz[0] for sz in sizes), default=0) + int(20 * s)
    lh = int(26 * s)
    h = lh * len(lines) + int(10 * s)
    roi = img[0:h, 0:w]
    roi[:] = (roi * 0.35 + np.array(color) * 0.65).astype(np.uint8)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (int(10 * s), int((i + 1) * lh)), cv2.FONT_HERSHEY_SIMPLEX, fs, WHITE, th, cv2.LINE_AA)
    return img


def draw_poly(img, poly, color=AMBER, fill_alpha: float = 0.0, thickness: int = 2) -> None:
    if fill_alpha > 0:
        layer = img.copy()
        cv2.fillPoly(layer, [poly], color)
        cv2.addWeighted(layer, fill_alpha, img, 1 - fill_alpha, 0, dst=img)
    cv2.polylines(img, [poly], True, color, max(thickness, int(thickness * scale_for(img))), cv2.LINE_AA)


def fit(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- video

@dataclass
class VideoInfo:
    fps: float
    width: int
    height: int
    frames: int


def video_info(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise UserError("Couldn't open the video. Try MP4 (H.264).")
    info = VideoInfo(cap.get(cv2.CAP_PROP_FPS) or 25.0, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                     int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    cap.release()
    if info.fps <= 1 or info.fps > 240:
        info.fps = 25.0
    return info


def frames(path: Path, stride: int = 1, max_side: int = 1280) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_index, time_seconds, frame) up to MAX_VIDEO_SECONDS."""
    info = video_info(path)
    cap = cv2.VideoCapture(str(path))
    limit = int(info.fps * config.max_video_seconds)
    i = 0
    try:
        while i < limit:
            ok, frame = cap.read()
            if not ok:
                break
            if i % stride == 0:
                yield i, i / info.fps, fit(frame, max_side)
            i += 1
    finally:
        cap.release()


class VideoWriter:
    """Writes browser-playable H.264 MP4 using the ffmpeg bundled with imageio-ffmpeg."""

    def __init__(self, path: Path, fps: float):
        self.path, self.fps, self._gen, self.size = path, fps, None, None
        self.first: np.ndarray | None = None

    def write(self, frame: np.ndarray) -> None:
        if self._gen is None:
            import imageio_ffmpeg
            h, w = frame.shape[:2]
            self.size = (w - w % 2, h - h % 2)
            self._gen = imageio_ffmpeg.write_frames(str(self.path), self.size, fps=self.fps, codec="libx264",
                                                    pix_fmt_in="bgr24", pix_fmt_out="yuv420p", quality=6,
                                                    macro_block_size=2, ffmpeg_log_level="error")
            self._gen.send(None)
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = cv2.resize(frame, self.size)
        if self.first is None:
            self.first = frame.copy()
        self._gen.send(np.ascontiguousarray(frame))

    def close(self) -> bool:
        if self._gen is not None:
            self._gen.close()
            return True
        return False


def video_output(ctx: Ctx, fps: float, name: str = "annotated") -> VideoWriter:
    return VideoWriter(ctx._name(name, ".mp4"), fps)


def finish_video(ctx: Ctx, writer: VideoWriter, caption: str = "Annotated video") -> None:
    if writer.close():
        poster = None
        if writer.first is not None:
            p = writer.path.with_suffix(".poster.jpg")
            cv2.imwrite(str(p), fit(writer.first, 1280), [cv2.IMWRITE_JPEG_QUALITY, 82])
            poster = ctx._url(p)
        ctx.result["video"] = {"url": ctx._url(writer.path), "caption": caption, "poster": poster}


def is_video(f: InputFile) -> bool:
    return f.kind == "video"
