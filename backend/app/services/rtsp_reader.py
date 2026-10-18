# app/services/rtsp_reader.py
"""Blocking frame source with reconnect handling (ported from lost-found).

Every method here blocks; camera workers call them through asyncio.to_thread
so the event loop stays free. Local files (sample:/file: sources) are looped
and read at their own frame rate, so they behave like a live camera.
"""

import logging
import os
import time
from typing import Optional, Tuple

import numpy as np

from app.core.config import config
from app.utils import camera_sources

logger = logging.getLogger(__name__)

# OpenCV reads this when a capture is created, so it must be set before the
# first VideoCapture() call.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    f"rtsp_transport;{config.rtsp_transport}|timeout;10000000|stimeout;10000000|max_delay;500000",
)

import cv2  # noqa: E402  - must follow the env var above


class FrameReader:
    """One video source. Reopens itself when the stream drops."""

    def __init__(self, source: str, workspace_id: Optional[int] = None) -> None:
        self.source = source
        self.workspace_id = workspace_id  # whose file: library to look in
        self.label = camera_sources.redact(source)
        self._capture: Optional[cv2.VideoCapture] = None
        self._loop_file = False
        self.consecutive_failures = 0
        self.frames_read = 0
        self._last_read_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def open(self) -> bool:
        """Returns False instead of raising, so callers can back off."""
        self.release()
        try:
            target, self._loop_file = camera_sources.resolve(self.source, self.workspace_id)
            capture = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
            if not capture.isOpened():
                logger.warning("Could not open source %s", self.label)
                capture.release()
                return False
            try:  # a tiny buffer keeps us at the live edge instead of replaying stale frames
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            self._capture = capture
            self.consecutive_failures = 0
            logger.info("Opened source %s (%s)", self.label, self.describe())
            return True
        except camera_sources.SourceError as e:
            logger.warning("Source %s is unavailable: %s", self.label, e)
            return False
        except Exception as e:
            logger.error("Error opening %s: %s", self.label, e, exc_info=True)
            return False

    def release(self) -> None:
        self._last_read_at = None
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None

    def describe(self) -> str:
        if not self.is_open:
            return "closed"
        w = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return f"{w}x{h} @ {self.source_fps:.1f}fps"

    @property
    def source_fps(self) -> float:
        if not self.is_open:
            return 0.0
        fps = self._capture.get(cv2.CAP_PROP_FPS) or 0.0
        return fps if 0 < fps < 240 else 0.0

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Decode one frame, first discarding every frame that arrived since
        the last read (grab() skips without decoding), so a slow analysis loop
        stays at the live edge instead of falling behind the source."""
        if not self.is_open:
            return False, None
        try:
            for _ in range(self._frames_to_skip()):
                if not self._capture.grab():
                    break
            ok, frame = self._capture.read()
            if (not ok or frame is None) and self._loop_file:
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            self._last_read_at = time.monotonic()
            if not ok or frame is None:
                self.consecutive_failures += 1
                return False, None
            self.consecutive_failures = 0
            self.frames_read += 1
            return True, frame
        except Exception as e:
            self.consecutive_failures += 1
            logger.warning("Read error on %s: %s", self.label, e)
            return False, None

    def _frames_to_skip(self) -> int:
        fps = self.source_fps
        if not fps or self._last_read_at is None:
            return 0
        elapsed = time.monotonic() - self._last_read_at
        # Capped so one stall can't turn into a multi-second grab loop.
        return min(int(elapsed * fps), int(fps * 2))

    def should_reconnect(self) -> bool:
        return self.consecutive_failures >= config.rtsp_read_failure_limit


def grab_single_frame(source: str, timeout: Optional[float] = None, workspace_id: Optional[int] = None) -> Optional[np.ndarray]:
    """Open a source just long enough to pull one frame (snapshots, the camera form's preview)."""
    deadline = time.time() + (timeout or config.rtsp_open_timeout)
    reader = FrameReader(source, workspace_id)
    try:
        if not reader.open():
            return None
        while time.time() < deadline:
            ok, frame = reader.read()
            if ok:
                return frame
        return None
    finally:
        reader.release()
