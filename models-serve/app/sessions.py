"""Tracking sessions. Ultralytics tracking keeps per-video state inside the model
(persist=True), so each video gets its own fresh model instance, kept until the
API ends the session or it sits idle for TRACK_SESSION_TTL seconds."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .codec import InputError
from .core.config import config
from .registry import manager


@dataclass
class Session:
    key: str
    model: Any
    used: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


class Sessions:
    def __init__(self) -> None:
        self._s: OrderedDict[str, Session] = OrderedDict()
        self._guard = threading.Lock()

    def get(self, sid: str, key: str) -> Session:
        if not sid or len(sid) > 64:
            raise InputError("A tracking session id is required.")
        with self._guard:
            self._expire()
            s = self._s.get(sid)
            if s is not None:
                if s.key != key:
                    raise InputError(f"Session {sid} tracks with {s.key}, not {key}.")
                self._s.move_to_end(sid)
                s.used = time.monotonic()
                return s
        # Loading can take a while (first download); don't hold the guard for it.
        s = Session(key, manager.fresh(key))
        with self._guard:
            s = self._s.setdefault(sid, s)
            while len(self._s) > config.max_track_sessions:
                self._s.popitem(last=False)
        return s

    def drop(self, sid: str) -> bool:
        with self._guard:
            return self._s.pop(sid, None) is not None

    def count(self) -> int:
        with self._guard:
            self._expire()
            return len(self._s)

    def _expire(self) -> None:
        cutoff = time.monotonic() - config.track_session_ttl
        for sid in [sid for sid, s in self._s.items() if s.used < cutoff]:
            del self._s[sid]


sessions = Sessions()
