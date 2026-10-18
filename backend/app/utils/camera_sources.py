# app/utils/camera_sources.py
"""Camera source URLs: what is allowed, where it points, and how to show it.

A source is one of
  rtsp://, rtsps://, http://, https://   a camera or stream on the network
  sample:<video>                          a lab sample video (street.mp4, fall.mp4), looped
  file:<name>                             a video under CAMERA_FILES_DIR, looped
Anything else (a bare path, file://, a webcam index) is refused: a workspace
admin must not be able to make the API open arbitrary files.
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


def validate(source: str) -> str:
    """The cleaned source string, or SourceError."""
    source = (source or "").strip()
    if source.startswith("sample:"):
        _local(SAMPLES_DIR, source[7:])
        return source
    if source.startswith("file:") and not source.startswith("file://"):
        _local(config.camera_files_dir, source[5:])
        return source
    parts = urlsplit(source)
    if parts.scheme.lower() not in NETWORK_SCHEMES:
        raise SourceError("Use an rtsp://, rtsps://, http(s):// URL, sample:<video> or file:<name>.")
    _check_host(parts.hostname)
    return source


def resolve(source: str) -> tuple[str, bool]:
    """(what OpenCV opens, whether it is a local file to loop)."""
    if source.startswith("sample:"):
        return str(_local(SAMPLES_DIR, source[7:])), True
    if source.startswith("file:"):
        return str(_local(config.camera_files_dir, source[5:])), True
    return source, False


def redact(source: str) -> str:
    """The URL without its password (rtsp://user:***@host/...), for people who
    may watch a camera but not edit it, and for logs."""
    parts = urlsplit(source)
    if parts.scheme not in NETWORK_SCHEMES or not parts.password:
        return source
    netloc = f"{parts.username}:***@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
