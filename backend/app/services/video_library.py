# app/services/video_library.py
"""Each workspace's video library: recordings uploaded in the console, kept
under CAMERA_FILES_DIR/ws<id>/, that a camera can loop as if it were live,
either as file:<name> or as the RTSP stream mediamtx serves for it
(rtsp://mediamtx:8554/files/ws<id>/<name>; see mediamtx/mediamtx.yml).
Files on disk are the whole state: there is no table."""

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import config
from app.utils import camera_sources

logger = logging.getLogger(__name__)

# Must match the library path pattern in mediamtx/mediamtx.yml.
EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mpg", ".mpeg")
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(mp4|mkv|mov|avi|webm|m4v|ts|mpg|mpeg)$")
SAMPLE_STREAMS = {"street.mp4": "street", "fall.mp4": "fall"}  # mediamtx paths of the lab samples


class VideoError(ValueError):
    """The message is shown to the user as is."""


def rtsp_url(workspace_id: int, name: str) -> Optional[str]:
    base = config.mediamtx_url.rstrip("/")
    return f"{base}/files/ws{workspace_id}/{name}" if base else None


def safe_name(filename: str, taken: set) -> str:
    """A name mediamtx can serve: letters, digits, - and _, a known extension,
    and unique in the folder (clip.mp4, clip-2.mp4, ...)."""
    path = Path(filename or "video.mp4")
    ext = path.suffix.lower()
    if ext not in EXTENSIONS:
        raise VideoError(f"Upload a video file ({', '.join(e[1:] for e in EXTENSIONS)}).")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", path.stem).strip("-_")[:60] or "video"
    name, n = f"{stem}{ext}", 2
    while name.lower() in taken:
        name, n = f"{stem}-{n}{ext}", n + 1
    return name


def folder(workspace_id: int) -> Path:
    return camera_sources.workspace_dir(workspace_id)


def list_videos(workspace_id: int) -> List[Dict[str, Any]]:
    d = folder(workspace_id)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if p.is_file() and _NAME.match(p.name):
            st = p.stat()
            out.append({
                "name": p.name,
                "size_bytes": st.st_size,
                "uploaded_at": datetime.fromtimestamp(st.st_mtime, timezone.utc),
                "file_source": f"file:{p.name}",
                "rtsp_url": rtsp_url(workspace_id, p.name),
            })
    return out


def sample_streams() -> List[Dict[str, Any]]:
    base = config.mediamtx_url.rstrip("/")
    return [
        {"name": name, "file_source": f"sample:{name}", "rtsp_url": f"{base}/{SAMPLE_STREAMS[name]}" if base else None}
        for name in camera_sources.sample_videos()
        if name in SAMPLE_STREAMS
    ]


def check_name(name: str) -> str:
    if not _NAME.match(name or ""):
        raise VideoError("No such video.")
    return name


def path_of(workspace_id: int, name: str) -> Path:
    return folder(workspace_id) / check_name(name)


def is_video(path: Path) -> bool:
    """Whether OpenCV (the same ffmpeg the cameras use) can decode a frame."""
    import cv2

    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    try:
        ok, frame = cap.read()
        return bool(ok and frame is not None)
    finally:
        cap.release()


def remove_workspace(workspace_id: int) -> None:
    shutil.rmtree(folder(workspace_id), ignore_errors=True)
