"""The live analyzers. Each mirrors the lab pipeline of the same name; where
the per-frame logic is shared (ZoneMonitor) both call the same code."""
from __future__ import annotations

from collections import defaultdict, deque

import cv2
import numpy as np

from ..core import banner, boxes_of, box, center, color_for, norm_points, side_of_line
from ..pipelines.common import ZoneMonitor, draw_dets, filter_classes
from ..pipelines.detection import PPE_ITEMS, parking_frame, ppe_frame
from ..pipelines.people import FallWatch, people_of
from ..pipelines.video import AbandonWatch, _crosses, _draw_line
from ..registry import ModelError, manager
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


@live
class FallDetection(_Tracking):
    name = "fall_detection"
    default_model = "yolo26-pose"
    events = {"fall": "Someone fell (a fast drop, then lying still)", "lying": "Someone is lying on the ground"}
    metrics = {"people": "avg", "fallen": "max"}

    def __init__(self, params):
        super().__init__(params)
        self.watch = FallWatch(float(self.p("lean", 60)), float(self.p("hold", 1.0)))

    def step(self, frame, t):
        r = self.tracker.track(frame, persist=True, conf=float(self.p("conf", 0.25)), tracker="bytetrack.yaml")[0]
        people = people_of(r)
        out, fallen, new = self.watch.step(frame, people, t)
        events = [LiveEvent(kind, "person", "critical", key if isinstance(key, int) and key < 2**31 else None)
                  for key, _, kind in new]
        return LiveOutput(out, events, {"people": len(people), "fallen": fallen})


@live
class AbandonedObject(LiveAnalyzer):
    name = "abandoned_object"
    events = {"abandoned": "An object was left with nobody near it"}
    metrics = {"watched": "avg", "unattended": "max"}

    def __init__(self, params):
        super().__init__(params)
        self.watch = AbandonWatch(set(self.p("objects", ["backpack", "handbag", "suitcase"])), float(self.p("seconds", 5)),
                                  float(self.p("radius", 3)))

    def step(self, frame, t):
        r = manager.get("yolo26-detect").predict(frame, conf=float(self.p("conf", 0.15)), imgsz=int(self.p("imgsz", 1280)))[0]
        out, new = self.watch.step(frame, boxes_of(r), t)
        unattended = sum(1 for m in self.watch.mem if m["alerted"])
        events = [LiveEvent("abandoned", m["cls"], "critical", None, round(m["conf"], 3),
                            {"box": [round(v) for v in m["box"]], "seconds_alone": round(t - m["alone_since"], 1)}) for m in new]
        return LiveOutput(out, events, {"watched": len(self.watch.mem), "unattended": unattended})


_PPE_PROMPTS = {"helmet": "hard hat", "vest": "safety vest", "mask": "face mask", "gloves": "gloves", "goggles": "safety goggles"}
PPE_COOLDOWN_S = 30.0


@live
class PpeCompliance(LiveAnalyzer):
    name = "ppe_compliance"
    default_model = "ppe-yolov8"
    events = {"ppe_violation": "A worker is missing required equipment (at most every 30 s per camera)"}
    metrics = {"workers": "avg", "violations": "max"}

    def __init__(self, params):
        super().__init__(params)
        self.required = self.p("required", ["helmet", "vest"]) or ["helmet", "vest"]
        try:  # same fallback as the lab: YOLOE-26 prompts when the PPE model can't be had
            manager.get(self.model_key)
        except ModelError:
            self.model_key = None
        self._last_event = -PPE_COOLDOWN_S

    def _detect(self, frame):
        conf = float(self.p("conf", 0.3))
        if self.model_key:
            dets = boxes_of(manager.get(self.model_key).predict(frame, conf=conf)[0])
            people = [d for d in dets if d["cls"].lower() == "person"]
            if not people:
                people = [d for d in boxes_of(manager.get("yolo26-detect").predict(frame, conf=conf)[0]) if d["cls"] == "person"]
            return people, [d for d in dets if d["cls"].lower() != "person"]
        people = [d for d in boxes_of(manager.get("yolo26-detect").predict(frame, conf=conf)[0]) if d["cls"] == "person"]
        gear = boxes_of(manager.get("yoloe26").yoloe([_PPE_PROMPTS[r] for r in self.required], frame, conf=max(0.1, conf - 0.15))[0])
        return people, gear

    def step(self, frame, t):
        people, gear = self._detect(frame)
        out, checks = ppe_frame(frame, people, gear, self.required)
        bad = [(p, missing) for p, ok, missing in checks if not ok]
        events = []
        if bad and t - self._last_event >= PPE_COOLDOWN_S:
            self._last_event = t
            missing = sorted({m for _, ms in bad for m in ms})
            events.append(LiveEvent("ppe_violation", "person", "warning", None, None,
                                    {"workers": len(people), "violations": len(bad), "missing": missing}))
        return LiveOutput(out, events, {"workers": len(people), "violations": len(bad)})


@live
class ParkingOccupancy(LiveAnalyzer):
    name = "parking_occupancy"
    events = {"lot_full": "Every drawn space became occupied"}
    metrics = {"vehicles": "avg", "occupied": "avg", "free": "avg"}

    def __init__(self, params):
        super().__init__(params)
        self._full = False

    def step(self, frame, t):
        r = manager.get(self.model_key).predict(frame, conf=float(self.p("conf", 0.3)))[0]
        out, vehicles, occ = parking_frame(frame, boxes_of(r), self.p("slots"))
        metrics = {"vehicles": vehicles}
        events = []
        if occ:
            metrics.update(occupied=sum(occ), free=len(occ) - sum(occ))
            full = all(occ)
            if full and not self._full:
                events.append(LiveEvent("lot_full", "parking", "info", None, None, {"spaces": len(occ)}))
            self._full = full
        return LiveOutput(out, events, metrics)
