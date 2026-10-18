"""The live analyzers. Each mirrors the lab pipeline of the same name; where
the per-frame logic is shared (ZoneMonitor) both call the same code."""
from __future__ import annotations

from collections import defaultdict, deque

import cv2
import numpy as np

from ..core import banner, boxes_of, box, center, color_for, norm_points, side_of_line
from ..pipelines.common import ZoneMonitor, draw_dets, filter_classes
from ..pipelines.video import _crosses, _draw_line
from ..registry import manager
from .base import LiveAnalyzer, LiveEvent, LiveOutput, live


class _Tracking(LiveAnalyzer):
    """Analyzers that follow objects across frames keep a tracking session on models-serve."""

    def __init__(self, params):
        super().__init__(params)
        self.tracker = manager.fresh(self.model_key)
        self._last_t: float | None = None

    def track(self, frame: np.ndarray) -> list[dict]:
        r = self.tracker.track(frame, persist=True, conf=float(self.p("conf", 0.25)), tracker="bytetrack.yaml")[0]
        return boxes_of(r)

    def dt(self, t: float) -> float:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        return dt

    def close(self) -> None:
        self.tracker.close()


@live
class Detect(LiveAnalyzer):
    name = "detect"
    metrics = {"objects": "avg", "count:<class>": "avg"}

    def step(self, frame, t):
        r = manager.get(self.model_key).predict(frame, conf=float(self.p("conf", 0.25)), imgsz=int(self.p("imgsz", 640)))[0]
        dets = filter_classes(boxes_of(r), self.p("classes", []))
        per_class: dict[str, int] = defaultdict(int)
        for d in dets:
            per_class[d["cls"]] += 1
        out = draw_dets(frame, dets)
        banner(out, [f"Objects: {len(dets)}"] + [f"{c}: {n}" for c, n in sorted(per_class.items(), key=lambda x: -x[1])[:4]])
        return LiveOutput(out, metrics={"objects": len(dets), **{f"count:{c}": n for c, n in per_class.items()}})


@live
class TrackCount(_Tracking):
    name = "track_count"
    metrics = {"in": "sum", "out": "sum", "tracked": "avg"}

    def __init__(self, params):
        super().__init__(params)
        self.last_side: dict[int, float] = {}
        self.trails: dict[int, deque] = defaultdict(lambda: deque(maxlen=30))
        self.n_in = self.n_out = 0

    def step(self, frame, t):
        h, w = frame.shape[:2]
        pts = norm_points(self.p("line") or [[0.5, 0.05], [0.5, 0.95]], w, h)
        a, b = tuple(pts[0]), tuple(pts[1])
        dets = filter_classes(self.track(frame), self.p("classes", ["person"]))
        out = frame.copy()
        _draw_line(out, a, b)
        crossed_in = crossed_out = 0
        live_ids = set()
        for d in dets:
            if d["id"] is None:
                continue
            live_ids.add(d["id"])
            c = center(d["box"])
            trail = self.trails[d["id"]]
            trail.append((int(c[0]), int(c[1])))
            s = side_of_line(c, a, b)
            prev = self.last_side.get(d["id"])
            if prev is not None and np.sign(prev) != np.sign(s) and s != 0 and len(trail) > 1 and _crosses(trail[-2], c, a, b):
                if s > 0:
                    crossed_in += 1
                else:
                    crossed_out += 1
            self.last_side[d["id"]] = s
            for k in range(1, len(trail)):
                cv2.line(out, trail[k - 1], trail[k], color_for(d["cls"]), 2, cv2.LINE_AA)
            box(out, d["box"], f"{d['cls']} #{d['id']}", color_for(d["cls"]))
        # Forget tracks that left, so memory stays flat on a camera that runs for months.
        for gone in set(self.last_side) - live_ids:
            if len(self.last_side) > 500:
                self.last_side.pop(gone, None)
                self.trails.pop(gone, None)
        self.n_in += crossed_in
        self.n_out += crossed_out
        banner(out, [f"In: {self.n_in}", f"Out: {self.n_out}", f"Tracked now: {len(live_ids)}"])
        return LiveOutput(out, metrics={"in": crossed_in, "out": crossed_out, "tracked": len(live_ids)})


@live
class RestrictedZone(_Tracking):
    name = "restricted_zone"
    events = {"zone_entry": "Someone or something entered the restricted zone"}
    metrics = {"in_zone": "max"}

    def __init__(self, params):
        super().__init__(params)
        self.monitor = ZoneMonitor(self.p("zone"), set(self.p("classes", ["person"]) or ["person"]))

    def step(self, frame, t):
        out, inside, entered = self.monitor.step(frame, self.track(frame), self.dt(t))
        if len(self.monitor.dwell) > 2000:  # keep only tracks still inside
            self.monitor.dwell = {k: v for k, v in self.monitor.dwell.items() if k in self.monitor.inside_ids}
        events = [
            LiveEvent("zone_entry", d["cls"], "warning", d["id"], round(d["conf"], 3), {"box": [round(v) for v in d["box"]]})
            for d in entered
        ]
        return LiveOutput(out, events, {"in_zone": inside})
