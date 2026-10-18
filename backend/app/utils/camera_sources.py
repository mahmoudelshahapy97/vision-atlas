# app/utils/camera_sources.py
"""Camera source URLs: what is allowed, where it points, and how to show it.

A source is one of
  rtsp://, rtsps://, http://, https://   a camera or stream on the network
  sample:<video>                          a lab sample video (street.mp4, fall.mp4), looped
  file:<name>                             a video of the workspace's library
                                          (CAMERA_FILES_DIR/ws<id>/), or one put
                                          straight into CAMERA_FILES_DIR, looped
Anything else (a bare path, file://, a webcam index) is refused: a workspace
admin must not be able to make the API open arbitrary files. The library is
also served over RTSP by mediamtx (rtsp://mediamtx:8554/files/ws<id>/<name>),
and those URLs only work for cameras of the same workspace.
"""

import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from app.core.config import config

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "vision" / "samples"
NETWORK_SCHEMES = {"rtsp", "rtsps", "http", "https"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"}


class SourceError(ValueError):
    """The message is shown to the user as is."""


def sample_videos() -> list[str]:
    return sorted(p.name for p in SAMPLES_DIR.glob("*.mp4"))


def _local(base: Path, name: str) -> Path:
    path = (base / name).resolve()
    if base.resolve() not in path.parents or path.suffix.lower() not in VIDEO_EXT or not path.is_file():
        raise SourceError(f"No video named '{name}' is available.")
    return path


def workspace_dir(workspace_id: int) -> Path:
    return config.camera_files_dir / f"ws{workspace_id}"


def _library_file(name: str, workspace_id: Optional[int]) -> Path:
    """file:<name>: the workspace's own copy first, then the shared folder."""
    if workspace_id is not None:
        try:
            return _local(workspace_dir(workspace_id), name)
        except SourceError:
            pass
    path = _local(config.camera_files_dir, name)
    if path.parent != config.camera_files_dir.resolve():  # not another workspace's ws<n>/ file
        raise SourceError(f"No video named '{name}' is available.")
    return path


def mediamtx_host() -> Optional[str]:
    return urlsplit(config.mediamtx_url).hostname if config.mediamtx_url else None


def _check_mediamtx_path(parts, workspace_id: Optional[int]) -> None:
    """Library streams on mediamtx belong to one workspace."""
    if parts.hostname != mediamtx_host() or not parts.path.startswith("/files/"):
        return
    owner = parts.path.split("/")[2] if parts.path.count("/") >= 3 else ""
    if workspace_id is None or owner != f"ws{workspace_id}":
        raise SourceError("That video belongs to another workspace.")


def _check_host(host: Optional[str]) -> None:
    """Cameras live on private networks, so those are fine; loopback and
    link-local (cloud metadata at 169.254.169.254) are not."""
    if not host:
        raise SourceError("The URL has no host.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return  # unresolvable now; the worker reports it when it tries to connect
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise SourceError("That address isn't allowed for a camera.")


def validate(source: str, workspace_id: Optional[int] = None) -> str:
    """The cleaned source string, or SourceError."""
    source = (source or "").strip()
    if source.startswith("sample:"):
        _local(SAMPLES_DIR, source[7:])
        return source
    if source.startswith("file:") and not source.startswith("file://"):
        _library_file(source[5:], workspace_id)
        return source
    parts = urlsplit(source)
    if parts.scheme.lower() not in NETWORK_SCHEMES:
        raise SourceError("Use an rtsp://, rtsps://, http(s):// URL, sample:<video> or file:<name>.")
    _check_mediamtx_path(parts, workspace_id)
    if parts.hostname != mediamtx_host():  # our own RTSP server is on purpose
        _check_host(parts.hostname)
    return source


def resolve(source: str, workspace_id: Optional[int] = None) -> tuple[str, bool]:
    """(what OpenCV opens, whether it is a local file to loop)."""
    if source.startswith("sample:"):
        return str(_local(SAMPLES_DIR, source[7:])), True
    if source.startswith("file:"):
        return str(_library_file(source[5:], workspace_id)), True
    return source, False


def redact(source: str) -> str:
    """The URL without its password (rtsp://user:***@host/...), for people who
    may watch a camera but not edit it, and for logs."""
    parts = urlsplit(source)
    if parts.scheme not in NETWORK_SCHEMES or not parts.password:
        return source
    netloc = f"{parts.username}:***@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
