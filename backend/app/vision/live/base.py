"""Live analyzers: lab pipelines adapted to an endless stream of camera frames.

A lab pipeline is a batch function over an uploaded file. A live analyzer is a
small stateful object fed one frame at a time by a camera worker
(app/services/stream_manager.py). It has the same name and the same settings
as its lab pipeline, so the console reuses the lab's parameter form, and the
geometry (zones, lines) is drawn the same way.

step() returns the annotated frame, any events (things an operator should
see: someone entered a zone, a bag was left behind) and metrics (numbers
sampled every frame: people in the zone, crossings). Like the rest of the
vision engine, analyzers never touch the database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import numpy as np

from ..core import PIPELINES, Pipeline, banner, resolve_params

# Settings that only make sense for a file: a camera's pace is its target_fps.
_BATCH_ONLY = {"stride"}


@dataclass
class LiveEvent:
    kind: str                       # zone_entry, line_cross, abandoned, fall, ...
    label: str                      # what it is about: a class name, "person"
    severity: str = "warning"       # info | warning | critical
    track_id: int | None = None
    confidence: float | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveOutput:
    frame: np.ndarray
    events: list[LiveEvent] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


class LiveAnalyzer:
    name: ClassVar[str]
    default_model: ClassVar[str] = "yolo26-detect"
    # kind -> description, and metric -> how a minute of samples is summarised ("avg", "max" or "sum")
    events: ClassVar[dict[str, str]] = {}
    metrics: ClassVar[dict[str, str]] = {}

    def __init__(self, params: dict[str, Any]):
        self.params = params
        m = params.get("model")
        self.model_key = m if isinstance(m, str) and m.startswith("custom:") else self.default_model

    def p(self, name: str, default: Any = None) -> Any:
        v = self.params.get(name, default)
        return default if v is None or v == "" else v

    def step(self, frame: np.ndarray, t: float) -> LiveOutput:
        raise NotImplementedError

    def close(self) -> None:
        """Release per-camera state on models-serve (tracking sessions)."""


LIVE_ANALYZERS: dict[str, type[LiveAnalyzer]] = {}


def live(cls: type[LiveAnalyzer]) -> type[LiveAnalyzer]:
    assert cls.name in PIPELINES, f"live analyzer {cls.name} has no lab pipeline"
    LIVE_ANALYZERS[cls.name] = cls
    return cls


def pipeline_of(name: str) -> Pipeline:
    return PIPELINES[name]


def live_params(name: str) -> list:
    return [p for p in PIPELINES[name].params if p.name not in _BATCH_ONLY]


def resolve(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults merged with the camera's settings, coerced and clamped like a
    lab run's (UserError for bad values)."""
    out = resolve_params(PIPELINES[name], None, params or {})
    for k in _BATCH_ONLY:
        out.pop(k, None)
    return out


def build(name: str, params: dict[str, Any]) -> LiveAnalyzer:
    return LIVE_ANALYZERS[name](resolve(name, params))


def public_list() -> list[dict[str, Any]]:
    out = []
    for name, cls in LIVE_ANALYZERS.items():
        pipe = PIPELINES[name]
        d = pipe.public()
        d["params"] = [p.public() for p in live_params(name)]
        d["events"] = cls.events
        d["metrics"] = cls.metrics
        out.append(d)
    return sorted(out, key=lambda d: d["title"])


def view_only(frame: np.ndarray, camera_name: str) -> LiveOutput:
    """A camera without a pipeline: the picture with its name and the time."""
    out = frame.copy()
    banner(out, [camera_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    return LiveOutput(out)

