"""Video analytics on YOLO26 + ByteTrack: line counting, speed, abandoned objects, football, anomalies."""
from __future__ import annotations

from collections import defaultdict, deque

import cv2
import numpy as np

from ..core import (AMBER, BLUE, CONF, GREEN, MEDIA, RED, STRIDE, VEHICLES, VIDEO, WHITE, Param, UserError, banner, box,
                    boxes_of, center, classes_param, color_for, finish_video, frames, iou, is_video, norm_points,
                    pipeline, side_of_line, video_info, video_output)
from ..registry import manager
from .common import draw_dets, filter_classes, heatmap_overlay, run_media


def _track(model, img, conf):
    return model.track(img, persist=True, conf=conf, tracker="bytetrack.yaml")[0]


def _line(ctx, img, default):
    h, w = img.shape[:2]
    pts = norm_points(ctx.p("line") or default, w, h)
    if len(pts) < 2:
        raise UserError("Draw the counting line (two points).")
    return tuple(pts[0]), tuple(pts[1])


def _draw_line(img, a, b, label_text=None):
    cv2.line(img, a, b, WHITE, 6, cv2.LINE_AA)
    cv2.line(img, a, b, AMBER, 3, cv2.LINE_AA)
    for p in (a, b):
        cv2.circle(img, p, 7, AMBER, -1, cv2.LINE_AA)


# ------------------------------------------------------------------ line counting

@pipeline("track_count", "Tracking and line counting",
          "Tracks each object with YOLO26 + ByteTrack and counts crossings of the line you draw, in each direction.",
          MEDIA, [classes_param(["person"], "Classes to count"),
                  Param("line", "Counting line", "line", [[0.5, 0.05], [0.5, 0.95]], help="Two points. 'In' = crossing from the left side of A→B to the right."),
                  CONF, STRIDE],
          models=["yolo26-detect"], custom_task="detect")
def track_count(ctx):
    f = ctx.file()
    names = ctx.p("classes", ["person"])
    if not is_video(f):
        img = f.read()
        dets = filter_classes(boxes_of(ctx.predict(ctx.model_key("yolo26-detect"), img, conf=float(ctx.p("conf", 0.25)))[0]), names)
        ctx.add_image(draw_dets(img, dets), "Detections")
        ctx.stat("Count in image", len(dets))
        ctx.note("Upload a video to track objects and count line crossings.")
        return
    model = manager.fresh(ctx.model_key("yolo26-detect"))
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    writer = video_output(ctx, info.fps / stride)
    last_side: dict[int, float] = {}
    trails: dict[int, deque] = defaultdict(lambda: deque(maxlen=30))
    seen: dict[int, str] = {}
    n_in = n_out = 0
    per_class = defaultdict(lambda: [0, 0])
    events, ts, ins, outs = [], [], [], []
    a = b = None
    for i, t, img in frames(f.path, stride):
        if a is None:
            a, b = _line(ctx, img, [[0.5, 0.05], [0.5, 0.95]])
        dets = filter_classes(boxes_of(_track(model, img, float(ctx.p("conf", 0.25)))), names)
        out = img.copy()
        _draw_line(out, a, b)
        for d in dets:
            if d["id"] is None:
                continue
            c = center(d["box"])
            seen[d["id"]] = d["cls"]
            trails[d["id"]].append((int(c[0]), int(c[1])))
            s = side_of_line(c, a, b)
            prev = last_side.get(d["id"])
            if prev is not None and np.sign(prev) != np.sign(s) and s != 0:
                # only count when the crossing point lies within the drawn segment
                if _crosses(trails[d["id"]][-2] if len(trails[d["id"]]) > 1 else c, c, a, b):
                    direction = "in" if s > 0 else "out"
                    if direction == "in":
                        n_in += 1
                        per_class[d["cls"]][0] += 1
                    else:
                        n_out += 1
                        per_class[d["cls"]][1] += 1
                    events.append([round(t, 2), d["id"], d["cls"], direction])
            last_side[d["id"]] = s
            pts = list(trails[d["id"]])
            for k in range(1, len(pts)):
                cv2.line(out, pts[k - 1], pts[k], color_for(d["cls"]), 2, cv2.LINE_AA)
            box(out, d["box"], f"{d['cls']} #{d['id']}", color_for(d["cls"]))
        banner(out, [f"In: {n_in}", f"Out: {n_out}", f"Tracked: {len(seen)}"])
        writer.write(out)
        ts.append(round(t, 2))
        ins.append(n_in)
        outs.append(n_out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Tracking and counting")
    ctx.stat("In", n_in, "good")
    ctx.stat("Out", n_out)
    ctx.stat("Net", n_in - n_out)
    ctx.stat("Unique objects", len(seen))
    uniq = defaultdict(int)
    for c in seen.values():
        uniq[c] += 1
    ctx.table("Per class", ["Class", "Unique tracks", "In", "Out"], [[c, uniq[c], *per_class[c]] for c in uniq], "counts.csv")
    if events:
        ctx.table("Crossings", ["Time (s)", "Track", "Class", "Direction"], events, "crossings.csv")
    ctx.chart("line", "Cumulative crossings", ts, [{"name": "In", "values": ins}, {"name": "Out", "values": outs}], "Time (s)")


def _crosses(p1, p2, a, b) -> bool:
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
    return ccw(p1, a, b) != ccw(p2, a, b) and ccw(p1, p2, a) != ccw(p1, p2, b)


# ------------------------------------------------------------------ speed estimation

@pipeline("speed_estimation", "Vehicle speed estimation",
          "Tracks vehicles and converts their movement to km/h using a reference line of known length that you draw along the road.",
          VIDEO, [classes_param(VEHICLES, "Vehicle classes"),
                  Param("line", "Calibration line", "line", [[0.2, 0.7], [0.8, 0.7]], help="Draw along the direction of travel over a stretch of known length."),
                  Param("distance_m", "Real length of that line (m)", "number", 20, 1, 500, 1),
                  Param("limit", "Speed limit (km/h)", "int", 60, 5, 200), CONF, STRIDE],
          models=["yolo26-detect"], custom_task="detect")
def speed_estimation(ctx):
    f = ctx.file()
    names = ctx.p("classes", VEHICLES)
    model = manager.fresh(ctx.model_key("yolo26-detect"))
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    writer = video_output(ctx, info.fps / stride)
    hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=int(info.fps)))
    speeds: dict[int, list] = defaultdict(list)
    cls_of: dict[int, str] = {}
    limit = int(ctx.p("limit", 60))
    mpp = None
    for i, t, img in frames(f.path, stride):
        if mpp is None:
            a, b = _line(ctx, img, [[0.2, 0.7], [0.8, 0.7]])
            px = float(np.hypot(b[0] - a[0], b[1] - a[1]))
            mpp = float(ctx.p("distance_m", 20)) / max(px, 1)
        dets = filter_classes(boxes_of(_track(model, img, float(ctx.p("conf", 0.25)))), names)
        out = img.copy()
        _draw_line(out, a, b)
        for d in dets:
            if d["id"] is None:
                continue
            c = ((d["box"][0] + d["box"][2]) / 2, d["box"][3])
            hist[d["id"]].append((t, c))
            cls_of[d["id"]] = d["cls"]
            h = hist[d["id"]]
            kmh = None
            if len(h) >= 4 and h[-1][0] - h[0][0] > 0.25:
                dist = np.hypot(h[-1][1][0] - h[0][1][0], h[-1][1][1] - h[0][1][1]) * mpp
                kmh = dist / (h[-1][0] - h[0][0]) * 3.6
                speeds[d["id"]].append(kmh)
            over = kmh is not None and kmh > limit
            box(out, d["box"], f"#{d['id']} " + (f"{kmh:.0f} km/h" if kmh is not None else d["cls"]), RED if over else GREEN)
        writer.write(out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Speed estimation")
    rows = []
    for k, v in speeds.items():
        if len(v) >= 3:
            med = float(np.median(v))
            rows.append([k, cls_of[k], round(med, 1), round(float(np.percentile(v, 90)), 1), "yes" if med > limit else "no"])
    rows.sort(key=lambda r: -r[2])
    ctx.stat("Vehicles measured", len(rows))
    if rows:
        ctx.stat("Fastest (median)", rows[0][2], unit="km/h")
        ctx.stat("Over the limit", sum(r[4] == "yes" for r in rows), "bad" if any(r[4] == "yes" for r in rows) else "good")
        ctx.table("Speeds", ["Track", "Class", "Median km/h", "90th pct km/h", "Over limit"], rows, "speeds.csv")
    ctx.note("Accuracy depends on calibration: draw the reference line along the lane, near where vehicles pass, "
             "and measure its true length on site or from a map.")


# ------------------------------------------------------------------ abandoned objects

@pipeline("abandoned_object", "Abandoned object detection",
          "Alerts when a bag or other object stays still with nobody near it for longer than the time you set.",
          VIDEO, [Param("objects", "Objects to watch", "multiselect", ["backpack", "handbag", "suitcase"],
                        options=["backpack", "handbag", "suitcase", "umbrella", "bottle", "laptop", "box"]),
                  Param("seconds", "Alert after unattended for (s)", "number", 5, 1, 120, 1),
                  Param("radius", "Owner distance (× object size)", "number", 3, 1, 10, 0.5), CONF, STRIDE],
          models=["yolo26-detect"])
def abandoned_object(ctx):
    f = ctx.file()
    watch = set(ctx.p("objects", ["backpack", "handbag", "suitcase"]))
    limit = float(ctx.p("seconds", 5))
    radius = float(ctx.p("radius", 3))
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    writer = video_output(ctx, info.fps / stride)
    mem: list[dict] = []   # static object candidates
    alerts = []
    for i, t, img in frames(f.path, stride):
        dets = boxes_of(ctx.predict("yolo26-detect", img, conf=float(ctx.p("conf", 0.25)))[0])
        objs = [d for d in dets if d["cls"] in watch]
        people = [d for d in dets if d["cls"] == "person"]
        for o in objs:
            m = max(mem, key=lambda m: iou(m["box"], o["box"]), default=None)
            if m is not None and iou(m["box"], o["box"]) > 0.5:
                m["last"], m["box"] = t, [0.8 * a + 0.2 * b for a, b in zip(m["box"], o["box"])]
            else:
                mem.append({"box": o["box"], "cls": o["cls"], "first": t, "last": t, "alone_since": None, "alerted": False})
        mem = [m for m in mem if t - m["last"] < 2.0]
        out = img.copy()
        for p in people:
            box(out, p["box"], None, BLUE, 1)
        for m in mem:
            c = center(m["box"])
            size = max(m["box"][2] - m["box"][0], m["box"][3] - m["box"][1])
            near = any(np.hypot(*(np.subtract(center(p["box"]), c))) < radius * size for p in people)
            if near:
                m["alone_since"] = None
            elif m["alone_since"] is None:
                m["alone_since"] = t
            alone = 0 if m["alone_since"] is None else t - m["alone_since"]
            danger = alone >= limit
            if danger and not m["alerted"]:
                m["alerted"] = True
                alerts.append([round(m["alone_since"] + limit, 1), m["cls"], [round(v) for v in m["box"]]])
            box(out, m["box"], f"{m['cls']} " + (f"UNATTENDED {alone:.0f}s" if danger else f"{alone:.0f}s"), RED if danger else AMBER)
        banner(out, [f"Watched objects: {len(mem)}", f"Alerts: {len(alerts)}"], (40, 40, 160) if alerts else (30, 30, 30))
        writer.write(out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Abandoned object watch")
    ctx.stat("Alerts", len(alerts), "bad" if alerts else "good")
    if alerts:
        ctx.table("Alerts", ["Time (s)", "Object", "Box"], alerts, "alerts.csv")


# ------------------------------------------------------------------ football analytics

@pipeline("football_analytics", "Football match analytics",
          "Tracks players and the ball, splits players into two teams by shirt color, and estimates possession and movement heatmaps.",
          MEDIA, [CONF, STRIDE], models=["yolo26-detect"])
def football_analytics(ctx):
    f = ctx.file()

    def shirt_color(img, b):
        x1, y1, x2, y2 = map(int, b)
        h = y2 - y1
        crop = img[max(0, y1 + int(0.15 * h)):max(0, y1 + int(0.5 * h)), max(0, x1):x2]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        grass = (hsv[..., 0] > 30) & (hsv[..., 0] < 90) & (hsv[..., 1] > 60)
        px = crop[~grass]
        if len(px) < 20:
            return None
        return cv2.cvtColor(np.uint8([[px.mean(0)]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)

    def assign(feats):
        data = np.array(feats, np.float32)
        if len(data) < 2:
            return None
        _, _, centers = cv2.kmeans(data, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 5,
                                   cv2.KMEANS_PP_CENTERS)
        return centers

    team_col = [(40, 40, 220), (220, 160, 40)]
    if not is_video(f):
        img = f.read()
        dets = boxes_of(ctx.predict("yolo26-detect", img, conf=float(ctx.p("conf", 0.25)))[0])
        players = [d for d in dets if d["cls"] == "person"]
        balls = [d for d in dets if d["cls"] == "sports ball"]
        feats = [(p, shirt_color(img, p["box"])) for p in players]
        centers = assign([x for _, x in feats if x is not None])
        out = img.copy()
        counts = [0, 0]
        for p, ft in feats:
            team = int(np.argmin([np.linalg.norm(ft - c) for c in centers])) if centers is not None and ft is not None else 0
            counts[team] += 1
            box(out, p["box"], f"team {'AB'[team]}", team_col[team])
        for bl in balls:
            box(out, bl["box"], "ball", WHITE)
        ctx.add_image(out, "Players and ball")
        ctx.stat("Players", len(players))
        ctx.stat("Team A", counts[0])
        ctx.stat("Team B", counts[1])
        ctx.stat("Ball found", "yes" if balls else "no")
        ctx.note("Upload a match video for tracking, possession and heatmaps.")
        return
    model = manager.fresh("yolo26-detect")
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    writer = video_output(ctx, info.fps / stride)
    feats_by_track: dict[int, list] = defaultdict(list)
    positions: dict[int, list] = defaultdict(list)
    centers = None
    possession = [0.0, 0.0]
    heat = None
    first = None
    dt = stride / info.fps
    for i, t, img in frames(f.path, stride):
        if heat is None:
            heat = np.zeros(img.shape[:2], np.float32)
            first = img.copy()
        r = _track(model, img, float(ctx.p("conf", 0.25)))
        dets = boxes_of(r)
        players = [d for d in dets if d["cls"] == "person" and d["id"] is not None]
        balls = sorted([d for d in dets if d["cls"] == "sports ball"], key=lambda d: -d["conf"])
        for p in players:
            ft = shirt_color(img, p["box"])
            if ft is not None and len(feats_by_track[p["id"]]) < 15:
                feats_by_track[p["id"]].append(ft)
            foot = (int((p["box"][0] + p["box"][2]) / 2), int(p["box"][3]))
            positions[p["id"]].append(foot)
            cv2.circle(heat, (min(foot[0], heat.shape[1] - 1), min(foot[1], heat.shape[0] - 1)), 18, 1.0, -1)
        if centers is None and len(feats_by_track) >= 6:
            centers = assign([np.mean(v, 0) for v in feats_by_track.values()])

        def team_of(tid):
            if centers is None or not feats_by_track.get(tid):
                return None
            m = np.mean(feats_by_track[tid], 0)
            return int(np.argmin([np.linalg.norm(m - c) for c in centers]))

        out = img.copy()
        holder = None
        if balls:
            bc = center(balls[0]["box"])
            near = min(players, key=lambda p: np.hypot(bc[0] - (p["box"][0] + p["box"][2]) / 2, bc[1] - p["box"][3]), default=None)
            if near is not None and np.hypot(bc[0] - (near["box"][0] + near["box"][2]) / 2, bc[1] - near["box"][3]) < 1.2 * (near["box"][3] - near["box"][1]):
                holder = near
                tm = team_of(near["id"])
                if tm is not None:
                    possession[tm] += dt
            box(out, balls[0]["box"], "ball", WHITE)
        for p in players:
            tm = team_of(p["id"])
            col = team_col[tm] if tm is not None else AMBER
            box(out, p["box"], f"{'AB'[tm] if tm is not None else '?'}{p['id']}" + (" ●" if holder is p else ""), col)
        tot = sum(possession) or 1
        banner(out, [f"Possession A {possession[0] / tot:.0%} · B {possession[1] / tot:.0%}"])
        writer.write(out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Match tracking")
    if first is not None and heat is not None and heat.max() > 0:
        ctx.add_image(heatmap_overlay(first, cv2.GaussianBlur(heat, (0, 0), 25), 0.55), "Player position heatmap")
    tot = sum(possession)
    ctx.stat("Players tracked", len(positions))
    if tot:
        ctx.stat("Possession A", round(possession[0] / tot * 100), unit="%")
        ctx.stat("Possession B", round(possession[1] / tot * 100), unit="%")
    else:
        ctx.note("The ball was not detected near players, so possession couldn't be measured. "
                 "Broadcast-wide shots make the ball tiny; a ball model fine-tuned on football footage helps.")
    rows = []
    for tid, pts in positions.items():
        if len(pts) > 5:
            d = float(np.sum(np.hypot(*np.diff(np.array(pts), axis=0).T)))
            rows.append([tid, len(pts), round(d)])
    rows.sort(key=lambda r: -r[2])
    if rows:
        ctx.table("Players", ["Track", "Frames seen", "Distance (px)"], rows[:40], "players.csv")
    ctx.note("Distances are in pixels. Map the pitch corners with a homography to convert to meters.")


# ------------------------------------------------------------------ video anomaly detection

@pipeline("video_anomaly", "Video anomaly detection",
          "Learns the normal amount of motion in the clip and flags moments that are unusually active or unusually still.",
          VIDEO, [Param("sensitivity", "Sensitivity (z-score)", "number", 3.5, 1.5, 8, 0.5, help="Lower flags more moments."),
                  Param("min_len", "Minimum event length (s)", "number", 0.5, 0, 10, 0.1), STRIDE], models=[])
def video_anomaly(ctx):
    f = ctx.file()
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    prev = None
    energy, ts, frames_cache = [], [], []
    for i, t, img in frames(f.path, stride, 960):
        g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (7, 7), 0)
        if prev is not None:
            diff = cv2.absdiff(g, prev)
            energy.append(float((diff > 18).mean()))
            ts.append(t)
        prev = g
        ctx.progress(0.5 * i / max(1, info.frames))
    if len(energy) < 10:
        raise UserError("The video is too short to learn what normal motion looks like.")
    e = np.array(energy)
    med = np.median(e)
    mad = np.median(np.abs(e - med)) * 1.4826 + 1e-4
    z = (e - med) / mad
    thr = float(ctx.p("sensitivity", 3.5))
    flag = np.abs(z) > thr
    events, start = [], None
    min_len = float(ctx.p("min_len", 0.5))
    for k, fl in enumerate(list(flag) + [False]):
        if fl and start is None:
            start = k
        elif not fl and start is not None:
            if ts[min(k, len(ts) - 1)] - ts[start] >= min_len:
                seg = z[start:k]
                events.append([round(ts[start], 2), round(ts[k - 1], 2), "more motion" if seg.mean() > 0 else "less motion",
                               round(float(seg[np.argmax(np.abs(seg))]), 1)])
            start = None
    # second pass: annotated video
    writer = video_output(ctx, info.fps / stride)
    prev = None
    k = -1
    for i, t, img in frames(f.path, stride, 960):
        g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (7, 7), 0)
        out = img.copy()
        if prev is not None:
            k += 1
            diff = cv2.absdiff(g, prev)
            out[diff > 18] = (out[diff > 18] * 0.5 + np.array(AMBER) * 0.5).astype(np.uint8)
            if k < len(flag) and flag[k]:
                cv2.rectangle(out, (0, 0), (out.shape[1] - 1, out.shape[0] - 1), RED, 12)
                banner(out, ["ANOMALY", f"z = {z[k]:.1f}"], (40, 40, 160))
        prev = g
        writer.write(out)
        ctx.progress(0.5 + 0.5 * i / max(1, info.frames))
    finish_video(ctx, writer, "Motion and anomalies")
    ctx.stat("Anomalous events", len(events), "bad" if events else "good")
    ctx.stat("Normal motion", round(float(med) * 100, 2), unit="% of pixels")
    ctx.chart("line", "Motion energy", [round(t, 2) for t in ts], [{"name": "Moving pixels %", "values": [round(v * 100, 3) for v in e]}], "Time (s)", "%")
    if events:
        ctx.table("Events", ["Start (s)", "End (s)", "Type", "Peak z"], events, "anomalies.csv")
    ctx.note("Statistical baseline on motion. For semantic anomalies (fights, falls, intrusions), combine with the "
             "fall detection or restricted-zone labs, or train a video model on your normal footage.")
