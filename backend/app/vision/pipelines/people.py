"""People, pose and face pipelines built on YOLO26-pose, YOLO26 tracking, YuNet and SFace."""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import (AMBER, BLUE, CONF, GREEN, IMAGE, MEDIA, RED, STRIDE, VIDEO, WHITE, Param, Slot, UserError, banner,
                    box, boxes_of, center, color_for, finish_video, frames, is_video, label, pipeline, point_in_poly,
                    polygons_param, draw_poly, scale_for, video_info, video_output)
from ..registry import manager
from .common import ZoneMonitor, run_media

# COCO keypoint indices
NOSE, LEYE, REYE, LEAR, REAR, LSH, RSH, LEL, REL, LWR, RWR, LHIP, RHIP, LKN, RKN, LAN, RAN = range(17)
SKELETON = [(LSH, RSH), (LSH, LEL), (LEL, LWR), (RSH, REL), (REL, RWR), (LSH, LHIP), (RSH, RHIP), (LHIP, RHIP),
            (LHIP, LKN), (LKN, LAN), (RHIP, RKN), (RKN, RAN), (NOSE, LEYE), (NOSE, REYE), (LEYE, LEAR), (REYE, REAR)]


def angle(a, b, c) -> float:
    """Angle ABC in degrees."""
    ba, bc = np.asarray(a) - b, np.asarray(c) - b
    cos = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def people_of(r, min_kp_conf: float = 0.3) -> list[dict]:
    out = []
    if r.keypoints is None or r.boxes is None:
        return out
    kxy = r.keypoints.xy.cpu().numpy()
    kc = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(kxy.shape[:2])
    b = r.boxes.xyxy.cpu().numpy()
    conf = r.boxes.conf.cpu().numpy()
    ids = r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else [None] * len(b)
    for i in range(len(b)):
        out.append({"box": b[i].tolist(), "conf": float(conf[i]), "kp": kxy[i], "kc": kc[i],
                    "id": None if ids[i] is None else int(ids[i]), "ok": kc[i] > min_kp_conf})
    return out


def draw_skeleton(img, p, color=AMBER) -> None:
    s = scale_for(img)
    for a, b in SKELETON:
        if p["ok"][a] and p["ok"][b]:
            cv2.line(img, tuple(map(int, p["kp"][a])), tuple(map(int, p["kp"][b])), color, max(2, int(2 * s)), cv2.LINE_AA)
    for j in range(17):
        if p["ok"][j]:
            cv2.circle(img, tuple(map(int, p["kp"][j])), max(3, int(3 * s)), WHITE, -1, cv2.LINE_AA)


def mid(p, a, b):
    return (p["kp"][a] + p["kp"][b]) / 2


def torso_angle(p) -> float | None:
    """Torso lean from vertical in degrees (0 = upright, 90 = horizontal)."""
    if not (p["ok"][LSH] or p["ok"][RSH]) or not (p["ok"][LHIP] or p["ok"][RHIP]):
        return None
    sh = mid(p, LSH, RSH) if p["ok"][LSH] and p["ok"][RSH] else p["kp"][LSH if p["ok"][LSH] else RSH]
    hp = mid(p, LHIP, RHIP) if p["ok"][LHIP] and p["ok"][RHIP] else p["kp"][LHIP if p["ok"][LHIP] else RHIP]
    v = sh - hp
    return float(np.degrees(np.arctan2(abs(v[0]), abs(v[1]) + 1e-6)))


def joint_angles(p) -> dict[str, float | None]:
    def a(i, j, k):
        return round(angle(p["kp"][i], p["kp"][j], p["kp"][k]), 1) if p["ok"][i] and p["ok"][j] and p["ok"][k] else None
    return {"L elbow": a(LSH, LEL, LWR), "R elbow": a(RSH, REL, RWR), "L knee": a(LHIP, LKN, LAN),
            "R knee": a(RHIP, RKN, RAN), "L hip": a(LSH, LHIP, LKN), "R hip": a(RSH, RHIP, RKN)}


def body_height(p) -> float:
    return max(1.0, p["box"][3] - p["box"][1])


def pose_predict(ctx, img, conf=0.3, track_model=None):
    if track_model is not None:
        r = track_model.track(img, persist=True, conf=conf, tracker="bytetrack.yaml")[0]
    else:
        r = ctx.predict(ctx.model_key("yolo26-pose"), img, conf=conf)[0]
    return people_of(r)


def largest(people):
    return max(people, key=lambda p: (p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1])) if people else None


def _tracker(ctx, f):
    return manager.fresh(ctx.model_key("yolo26-pose")) if is_video(f) else None


# ------------------------------------------------------------------ pose

@pipeline("pose", "YOLO26 pose estimation", "17 body keypoints per person with joint angles.",
          MEDIA, [CONF, STRIDE], models=["yolo26-pose"], custom_task="pose")
def pose(ctx):
    def fn(img, t, st):
        people = pose_predict(ctx, img, float(ctx.p("conf", 0.25)))
        out = img.copy()
        for i, p in enumerate(people):
            draw_skeleton(out, p, color_for(str(i)))
            box(out, p["box"], f"person {i + 1}", color_for(str(i)), 1)
        st["people"] = people
        st["max"] = max(st.get("max", 0), len(people))
        return out

    st = run_media(ctx, fn, caption="Pose")
    people = st.get("people", [])
    ctx.stat("People" if not st.get("video") else "Most people in one frame", st.get("max", 0))
    if people and not st.get("video"):
        rows = []
        for i, p in enumerate(people):
            ja = joint_angles(p)
            rows.append([i + 1, round(p["conf"], 2), torso_angle(p) and round(torso_angle(p), 1), *ja.values()])
        ctx.table("Joint angles (degrees)", ["Person", "Conf", "Torso lean", *joint_angles(people[0]).keys()], rows, "angles.csv")
        ctx.add_json([{"person": i + 1, "keypoints": p["kp"].round(1).tolist(), "confidence": p["kc"].round(3).tolist()}
                      for i, p in enumerate(people)], "keypoints.json")


# ------------------------------------------------------------------ fall detection

@pipeline("fall_detection", "Fall detection",
          "Flags people lying down or falling, from torso angle, box shape and (in video) a fast drop followed by lying still.",
          MEDIA, [Param("lean", "Fallen if torso leans more than (°)", "int", 60, 30, 85),
                  Param("hold", "Alert after lying for (s)", "number", 1.0, 0, 10, 0.5), CONF, STRIDE],
          models=["yolo26-pose"], custom_task="pose")
def fall_detection(ctx):
    f = ctx.file()
    tracker = _tracker(ctx, f)
    lean = float(ctx.p("lean", 60))
    hold = float(ctx.p("hold", 1.0))

    def fn(img, t, st):
        people = pose_predict(ctx, img, float(ctx.p("conf", 0.25)), tracker)
        out = img.copy()
        n_fallen = 0
        tracks = st.setdefault("tracks", {})
        for p in people:
            ta = torso_angle(p)
            w, h = p["box"][2] - p["box"][0], p["box"][3] - p["box"][1]
            lying = (ta is not None and ta > lean) or (w / max(h, 1) > 1.3)
            key = p["id"] if p["id"] is not None else id(p)
            tr = tracks.setdefault(key, {"since": None, "alerted": False, "hip": [], "fall_at": None})
            hip_y = (p["box"][1] + p["box"][3]) / 2
            tr["hip"].append((t, hip_y / max(h, 1)))
            tr["hip"] = tr["hip"][-30:]
            if lying:
                tr["since"] = tr["since"] if tr["since"] is not None else t
            else:
                tr["since"], tr["alerted"] = None, False
            fallen = lying and (not st["video"] or t - tr["since"] >= hold)
            if fallen and st["video"] and not tr["alerted"]:
                tr["alerted"] = True
                drop = [y for tt, y in tr["hip"] if t - tt <= 2.0]
                st.setdefault("events", []).append([round(tr["since"], 1), key, "fall" if drop and max(drop) - min(drop) > 0.25 else "lying"])
            n_fallen += fallen
            draw_skeleton(out, p, RED if fallen else GREEN)
            box(out, p["box"], ("FALL" if fallen else "upright") + (f" #{p['id']}" if p["id"] is not None else "")
                + (f" {ta:.0f}°" if ta is not None else ""), RED if fallen else GREEN)
        st["fallen"] = max(st.get("fallen", 0), n_fallen)
        st["people"] = len(people)
        banner(out, [f"People: {len(people)}", f"Fallen: {n_fallen}"], (40, 40, 160) if n_fallen else (30, 30, 30))
        return out

    st = run_media(ctx, fn, caption="Fall detection")
    ctx.stat("People", st.get("people", 0))
    ctx.stat("Fallen" if not st.get("video") else "Most fallen at once", st.get("fallen", 0), "bad" if st.get("fallen") else "good")
    if st.get("events"):
        ctx.stat("Alerts", len(st["events"]), "bad")
        ctx.table("Alerts", ["Time (s)", "Track", "Type"], st["events"], "falls.csv")
    ctx.note("Rule-based on YOLO26 pose. Validate on footage from your own cameras before relying on alerts.")


# ------------------------------------------------------------------ exercise counter

EXERCISES = {  # joint triplets per side, angle when "down", angle when "up"
    "squat": ((LHIP, LKN, LAN), (RHIP, RKN, RAN), 100, 160, "knee"),
    "push-up": ((LSH, LEL, LWR), (RSH, REL, RWR), 95, 150, "elbow"),
    "biceps curl": ((LSH, LEL, LWR), (RSH, REL, RWR), 150, 55, "elbow"),
    "lunge": ((LHIP, LKN, LAN), (RHIP, RKN, RAN), 105, 160, "knee"),
}


@pipeline("exercise_counter", "Exercise rep counter",
          "Counts repetitions and tracks the working joint angle with YOLO26 pose.",
          MEDIA, [Param("exercise", "Exercise", "select", "squat", options=list(EXERCISES)), CONF, STRIDE],
          models=["yolo26-pose"])
def exercise_counter(ctx):
    ex = ctx.p("exercise", "squat")
    left, right, down_at, up_at, joint = EXERCISES[ex]
    curl = down_at > up_at  # for curls the "down" position has the larger angle

    def side_angle(p):
        vals = []
        for tri in (left, right):
            if all(p["ok"][j] for j in tri):
                vals.append((float(p["kc"][list(tri)].mean()), angle(*[p["kp"][j] for j in tri])))
        return max(vals)[1] if vals else None

    def fn(img, t, st):
        p = largest(pose_predict(ctx, img, float(ctx.p("conf", 0.25))))
        out = img.copy()
        a = side_angle(p) if p else None
        st.setdefault("t", []).append(round(t, 2))
        st.setdefault("a", []).append(None if a is None else round(a, 1))
        if p:
            draw_skeleton(out, p)
        if a is not None:
            low = a > down_at if curl else a < down_at
            high = a < up_at if curl else a > up_at
            phase = st.get("phase", "up")
            if phase == "up" and low:
                st["phase"] = "down"
            elif phase == "down" and high:
                st["phase"] = "up"
                st["reps"] = st.get("reps", 0) + 1
                st.setdefault("rep_times", []).append(round(t, 1))
            st.setdefault("angles", []).append(a)
        banner(out, [ex.capitalize(), f"Reps: {st.get('reps', 0)}", f"{joint} angle: {a:.0f}°" if a is not None else f"{joint}: not visible",
                     f"Phase: {st.get('phase', 'up')}"])
        return out

    st = run_media(ctx, fn, caption=f"{ex} counter")
    if st.get("video"):
        ctx.stat("Reps", st.get("reps", 0), "good")
        if st.get("angles"):
            ctx.stat(f"Deepest {joint} angle", round(max(st["angles"]) if curl else min(st["angles"]), 1), unit="°")
        ctx.chart("line", f"{joint.capitalize()} angle over time", st["t"], [{"name": f"{joint} angle", "values": st["a"]}], "Time (s)", "Degrees")
        if st.get("rep_times"):
            ctx.table("Repetitions", ["Rep", "Completed at (s)"], [[i + 1, t] for i, t in enumerate(st["rep_times"])])
    else:
        a = st["a"][-1] if st.get("a") else None
        ctx.stat(f"{joint.capitalize()} angle", a if a is not None else "not visible", unit="°" if a is not None else None)
        ctx.note("Upload a video to count repetitions.")


# ------------------------------------------------------------------ gait analysis

@pipeline("gait_analysis", "Gait analysis",
          "Steps, cadence and left/right symmetry from ankle movement (video of one person walking, side view works best).",
          VIDEO, [CONF], models=["yolo26-pose"])
def gait_analysis(ctx):
    f = ctx.file()
    info = video_info(f.path)
    writer = video_output(ctx, info.fps)
    ts, sep, lx, rx = [], [], [], []
    for i, t, img in frames(f.path):
        p = largest(pose_predict(ctx, img, float(ctx.p("conf", 0.25))))
        out = img.copy()
        if p is not None and p["ok"][LAN] and p["ok"][RAN]:
            draw_skeleton(out, p)
            h = body_height(p)
            ts.append(t)
            sep.append(float(p["kp"][LAN][0] - p["kp"][RAN][0]) / h)
            lx.append(float(p["kp"][LAN][1]))
            rx.append(float(p["kp"][RAN][1]))
        writer.write(out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Gait tracking")
    if len(ts) < 10:
        raise UserError("Couldn't see both ankles in enough frames. Film the whole body, ideally from the side.")
    s = np.convolve(np.asarray(sep), np.ones(3) / 3, mode="same")
    # a step happens at each extreme of the signed ankle separation
    peaks = [i for i in range(1, len(s) - 1) if abs(s[i]) > 0.08 and abs(s[i]) >= abs(s[i - 1]) and abs(s[i]) >= abs(s[i + 1])
             and (i < 2 or np.sign(s[i]) != 0)]
    steps, last_sign = [], 0
    for i in peaks:
        sg = int(np.sign(s[i]))
        if sg != last_sign:
            steps.append((ts[i], "left" if sg > 0 else "right"))
            last_sign = sg
    duration = ts[-1] - ts[0]
    ctx.stat("Steps", len(steps))
    cadence = len(steps) / duration * 60 if duration > 0 else 0
    ctx.stat("Cadence", round(cadence), unit="steps/min")
    lefts = np.diff([t for t, sd in steps if sd == "left"])
    rights = np.diff([t for t, sd in steps if sd == "right"])
    if len(lefts) and len(rights):
        sym = min(lefts.mean(), rights.mean()) / max(lefts.mean(), rights.mean()) * 100
        ctx.stat("Step-time symmetry", round(sym), "good" if sym > 90 else "warn", "%")
    ctx.stat("Analyzed", round(duration, 1), unit="s")
    ctx.chart("line", "Ankle separation (body heights)", [round(t, 2) for t in ts], [{"name": "Left − right ankle", "values": [round(float(v), 3) for v in s]}], "Time (s)")
    ctx.table("Steps", ["#", "Time (s)", "Leading foot"], [[i + 1, round(t, 2), sd] for i, (t, sd) in enumerate(steps)], "steps.csv")
    ctx.note("For research or rehabilitation tracking, not clinical diagnosis.")


# ------------------------------------------------------------------ action recognition

def posture(p) -> str:
    ta = torso_angle(p)
    ja = joint_angles(p)
    knees = [a for a in (ja["L knee"], ja["R knee"]) if a is not None]
    hips = [a for a in (ja["L hip"], ja["R hip"]) if a is not None]
    w, h = p["box"][2] - p["box"][0], p["box"][3] - p["box"][1]
    if (ta is not None and ta > 60) or w > 1.3 * h:
        return "lying"
    if (knees and min(knees) < 120 and hips and min(hips) < 130) or (hips and min(hips) < 115):
        return "sitting"
    return "standing"


@pipeline("action_recognition", "Action recognition",
          "Labels each person as standing, sitting, lying, walking, running or jumping from pose and motion.",
          MEDIA, [CONF, STRIDE], models=["yolo26-pose"])
def action_recognition(ctx):
    f = ctx.file()
    tracker = _tracker(ctx, f)

    def fn(img, t, st):
        people = pose_predict(ctx, img, float(ctx.p("conf", 0.25)), tracker)
        out = img.copy()
        tr = st.setdefault("tracks", {})
        for p in people:
            act = posture(p)
            if st["video"] and p["id"] is not None:
                hist = tr.setdefault(p["id"], {"pts": [], "time": {}})
                c = np.array(center(p["box"]))
                hist["pts"].append((t, c, body_height(p), p["box"][3]))
                hist["pts"] = [x for x in hist["pts"] if t - x[0] <= 1.0]
                if act == "standing" and len(hist["pts"]) > 3:
                    dt = hist["pts"][-1][0] - hist["pts"][0][0]
                    speed = np.linalg.norm(hist["pts"][-1][1] - hist["pts"][0][1]) / hist["pts"][-1][2] / max(dt, 1e-3)
                    rise = (hist["pts"][0][3] - hist["pts"][-1][3]) / hist["pts"][-1][2]
                    act = "jumping" if rise > 0.15 else "running" if speed > 1.6 else "walking" if speed > 0.35 else "standing"
                hist["time"][act] = hist["time"].get(act, 0) + 1 / st.get("fps", 25)
            draw_skeleton(out, p, color_for(act))
            box(out, p["box"], act + (f" #{p['id']}" if p["id"] is not None else ""), color_for(act))
            st.setdefault("acts", []).append(act)
        st["last"] = [(p.get("id"), posture(p)) for p in people]
        return out

    st = run_media(ctx, fn, caption="Actions")
    if st.get("video") and st.get("tracks"):
        rows = [[k, *[round(v["time"].get(a, 0), 1) for a in ("standing", "walking", "running", "jumping", "sitting", "lying")]]
                for k, v in st["tracks"].items() if sum(v["time"].values()) > 0.3]
        ctx.stat("People tracked", len(rows))
        ctx.table("Seconds per action", ["Track", "Standing", "Walking", "Running", "Jumping", "Sitting", "Lying"], rows, "actions.csv")
    else:
        acts = [a for _, a in st.get("last", [])]
        ctx.stat("People", len(acts))
        for a in sorted(set(acts)):
            ctx.stat(a.capitalize(), acts.count(a))
        ctx.note("Upload a video to also detect walking, running and jumping.")
    ctx.note("Rule-based. For more actions (e.g. fighting, waving), train a video model such as VideoMAE on your clips.")


# ------------------------------------------------------------------ gesture control

GESTURES = {"right hand up": "next slide", "left hand up": "previous slide", "both hands up": "play / pause",
            "arms out (T)": "stop", "none": "—"}


def gesture_of(p) -> str:
    if p is None:
        return "none"
    k, ok = p["kp"], p["ok"]
    sh = body_height(p) * 0.05
    # the person's right side appears on the image's left for a camera facing them
    rup = ok[RWR] and ok[RSH] and k[RWR][1] < k[RSH][1] - sh * 2
    lup = ok[LWR] and ok[LSH] and k[LWR][1] < k[LSH][1] - sh * 2
    if rup and lup:
        return "both hands up"
    if ok[LWR] and ok[RWR] and ok[LSH] and ok[RSH]:
        width = abs(k[LSH][0] - k[RSH][0])
        level = abs(k[LWR][1] - k[LSH][1]) < width * 0.4 and abs(k[RWR][1] - k[RSH][1]) < width * 0.4
        if level and abs(k[LWR][0] - k[RWR][0]) > width * 2.6:
            return "arms out (T)"
    if rup:
        return "right hand up"
    if lup:
        return "left hand up"
    return "none"


@pipeline("gesture_control", "Gesture control",
          "Recognizes arm gestures and maps them to commands, e.g. right hand up = next slide.",
          MEDIA, [Param("hold", "Hold gesture for (s)", "number", 0.5, 0, 3, 0.1), CONF, STRIDE], models=["yolo26-pose"])
def gesture_control(ctx):
    hold = float(ctx.p("hold", 0.5))

    def fn(img, t, st):
        p = largest(pose_predict(ctx, img, float(ctx.p("conf", 0.25))))
        g = gesture_of(p)
        out = img.copy()
        if p:
            draw_skeleton(out, p, GREEN if g != "none" else AMBER)
        if g != st.get("cur"):
            st["cur"], st["since"], st["fired"] = g, t, False
        if g != "none" and not st.get("fired") and (not st["video"] or t - st["since"] >= hold):
            st["fired"] = True
            st.setdefault("events", []).append([round(t, 2), g, GESTURES[g]])
        st["last"] = g
        banner(out, [f"Gesture: {g}", f"Command: {GESTURES[g]}"])
        return out

    st = run_media(ctx, fn, caption="Gestures")
    ctx.stat("Gesture" if not st.get("video") else "Commands", st.get("last") if not st.get("video") else len(st.get("events", [])))
    if not st.get("video"):
        ctx.stat("Command", GESTURES[st.get("last", "none")])
    if st.get("events"):
        ctx.table("Commands", ["Time (s)", "Gesture", "Command"], st["events"], "gestures.csv")
    ctx.note("Arm gestures from body pose. Finger-level gestures need a hand-landmark model such as MediaPipe Hands.")


# ------------------------------------------------------------------ restricted zone

@pipeline("restricted_zone", "Restricted-zone monitoring",
          "Raises a violation when a person (or any class you pick) enters the zone you draw.",
          MEDIA, [Param("zone", "Restricted zone", "polygon", [[0.6, 0.35], [0.98, 0.35], [0.98, 0.98], [0.6, 0.98]],
                        help="Click points on the image to outline the zone."),
                  Param("classes", "Who to watch", "multiselect", ["person"], options=["person", "car", "truck", "forklift", "bicycle", "motorcycle"]),
                  CONF, STRIDE],
          models=["yolo26-detect"], custom_task="detect")
def restricted_zone(ctx):
    f = ctx.file()
    tracker = manager.fresh(ctx.model_key("yolo26-detect")) if is_video(f) else None
    monitor = ZoneMonitor(ctx.p("zone"), set(ctx.p("classes", ["person"]) or ["person"]))

    def fn(img, t, st):
        if monitor.zone(img) is None:
            raise UserError("Draw the restricted zone on the image first.")
        if tracker is not None:
            r = tracker.track(img, persist=True, conf=float(ctx.p("conf", 0.25)))[0]
        else:
            r = ctx.predict(ctx.model_key("yolo26-detect"), img, conf=float(ctx.p("conf", 0.25)))[0]
        out, inside, entered = monitor.step(img, boxes_of(r), 1 / st.get("fps", 25))
        for d in entered:
            st.setdefault("events", []).append([round(t, 1), d["id"], d["cls"], "entered"])
        st["max_inside"] = max(st.get("max_inside", 0), inside)
        return out

    st = run_media(ctx, fn, caption="Restricted zone")
    ctx.stat("In zone now" if not st.get("video") else "Most in zone at once", st.get("max_inside", 0),
             "bad" if st.get("max_inside") else "good")
    if st.get("events"):
        ctx.stat("Entries", len(st["events"]), "bad")
        rows = [[*e, round(monitor.dwell.get(e[1], 0), 1)] for e in st["events"]]
        ctx.table("Zone entries", ["Time (s)", "Track", "Class", "Event", "Seconds inside"], rows, "zone_events.csv")


# ------------------------------------------------------------------ faces (YuNet + SFace)

def detect_faces(img, score: float = 0.6) -> list[dict]:
    path = manager.get("yunet")
    h, w = img.shape[:2]
    s = 1.0
    if max(h, w) > 1280:
        s = 1280 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)))
    det = cv2.FaceDetectorYN.create(path, "", (img.shape[1], img.shape[0]), score, 0.3, 5000)
    _, faces = det.detect(img)
    out = []
    for f in (faces if faces is not None else []):
        f = f.copy()
        f[:14] /= s
        x, y, fw, fh = f[:4]
        lm = f[4:14].reshape(5, 2)  # right eye, left eye, nose, right mouth, left mouth
        out.append({"box": [float(x), float(y), float(x + fw), float(y + fh)], "lm": lm, "score": float(f[14]), "raw": f})
    return sorted(out, key=lambda d: -(d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]))


def head_pose(face) -> tuple[float, float, float]:
    """Approximate yaw ratio, pitch ratio and roll (°) from the 5 landmarks."""
    re, le, nose, rm, lm = face["lm"]
    eye_mid = (re + le) / 2
    eye_d = np.linalg.norm(le - re) + 1e-6
    mouth_mid = (rm + lm) / 2
    yaw = float((nose[0] - eye_mid[0]) / eye_d)
    pitch = float((nose[1] - eye_mid[1]) / (np.linalg.norm(mouth_mid - eye_mid) + 1e-6))
    roll = float(np.degrees(np.arctan2(le[1] - re[1], le[0] - re[0])))
    return yaw, pitch, roll


def draw_face(img, face, text=None, color=AMBER):
    box(img, face["box"], text, color)
    for pt in face["lm"]:
        cv2.circle(img, tuple(map(int, pt)), max(2, int(3 * scale_for(img))), (60, 220, 255), -1, cv2.LINE_AA)


def face_feature(img, face) -> np.ndarray:
    rec = cv2.FaceRecognizerSF.create(manager.get("sface"), "")
    return rec.feature(rec.alignCrop(img, face["raw"])), rec


@pipeline("face_landmarks", "Face detection and landmarks",
          "Finds faces with YuNet and marks eyes, nose and mouth corners, with head roll and turn estimates.",
          IMAGE, [Param("score", "Face confidence", "number", 0.6, 0.3, 0.95, 0.05)], models=["yunet", "sface"])
def face_landmarks(ctx):
    img = ctx.image()
    faces = detect_faces(img, float(ctx.p("score", 0.6)))
    out = img.copy()
    rows, crops = [], []
    rec = cv2.FaceRecognizerSF.create(manager.get("sface"), "") if faces else None
    for i, fc in enumerate(faces):
        yaw, pitch, roll = head_pose(fc)
        draw_face(out, fc, f"face {i + 1}")
        rows.append([i + 1, round(fc["score"], 2), round(float(np.linalg.norm(fc["lm"][1] - fc["lm"][0]))), round(roll, 1),
                     "left" if yaw < -0.25 else "right" if yaw > 0.25 else "frontal", *[round(float(v), 1) for v in fc["lm"].ravel()]])
        if i < 8:
            crops.append(rec.alignCrop(img, fc["raw"]))
    ctx.add_image(out, "Faces and landmarks")
    for i, c in enumerate(crops):
        ctx.add_image(c, f"Aligned face {i + 1}")
    ctx.stat("Faces", len(faces))
    if rows:
        ctx.table("Faces", ["Face", "Score", "Eye distance (px)", "Roll (°)", "Facing", "R eye x", "R eye y", "L eye x", "L eye y",
                            "Nose x", "Nose y", "R mouth x", "R mouth y", "L mouth x", "L mouth y"], rows, "landmarks.csv")
    ctx.note("YuNet gives 5 landmarks. Dense 68/468-point meshes need a model like MediaPipe Face Mesh.")


@pipeline("face_verification", "Face verification",
          "Compares the main face in two photos and says whether they are likely the same person (SFace embeddings).",
          [Slot("a", "Photo A"), Slot("b", "Photo B")],
          [Param("threshold", "Match threshold (cosine)", "number", 0.363, 0.2, 0.7, 0.01,
                 help="OpenCV's recommended value is 0.363. Higher = stricter.")],
          models=["yunet", "sface"])
def face_verification(ctx):
    a, b = ctx.image("a"), ctx.image("b")
    fa, fb = detect_faces(a), detect_faces(b)
    if not fa or not fb:
        raise UserError(f"No face found in photo {'A' if not fa else 'B'}. Use a clear, front-facing photo.")
    ea, rec = face_feature(a, fa[0])
    eb, _ = face_feature(b, fb[0])
    score = float(rec.match(ea, eb, cv2.FaceRecognizerSF_FR_COSINE))
    thr = float(ctx.p("threshold", 0.363))
    same = score >= thr
    ca, cb = rec.alignCrop(a, fa[0]["raw"]), rec.alignCrop(b, fb[0]["raw"])
    pair = cv2.hconcat([cv2.resize(ca, (224, 224)), np.full((224, 12, 3), 255, np.uint8), cv2.resize(cb, (224, 224))])
    pair = cv2.copyMakeBorder(pair, 0, 44, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(pair, f"{'SAME PERSON' if same else 'DIFFERENT'}  {score:.3f}", (10, 254), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (40, 140, 40) if same else (40, 40, 200), 2, cv2.LINE_AA)
    ctx.add_image(pair, "Aligned faces")
    ctx.stat("Result", "Same person" if same else "Different people", "good" if same else "bad")
    ctx.stat("Similarity", round(score, 3))
    ctx.stat("Threshold", thr)
    ctx.note("Use only with the consent of the people pictured, and keep a human in the loop for decisions.")


@pipeline("face_liveness", "Face presentation-attack check",
          "Crops the face with YuNet and runs your trained live/spoof classifier. Without one, it reports image cues "
          "(screen moiré, blur, color) that often indicate a replay or print.",
          IMAGE, [], models=["yunet"], custom_task="classify")
def face_liveness(ctx):
    img = ctx.image()
    faces = detect_faces(img)
    if not faces:
        raise UserError("No face found.")
    fc = faces[0]
    x1, y1, x2, y2 = map(int, fc["box"])
    pad = int(0.2 * (x2 - x1))
    crop = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
    out = img.copy()
    key = ctx.params.get("model")
    if isinstance(key, str) and key.startswith("custom:"):
        r = ctx.predict(key, crop)[0]
        top = int(r.probs.top1)
        name, p = r.names[top], float(r.probs.top1conf)
        live = "live" in name.lower() or "real" in name.lower()
        draw_face(out, fc, f"{name} {p:.2f}", GREEN if live else RED)
        ctx.stat("Prediction", name, "good" if live else "bad")
        ctx.stat("Confidence", round(p, 3))
    else:
        g = cv2.cvtColor(cv2.resize(crop, (256, 256)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        spec = np.abs(np.fft.fftshift(np.fft.fft2(g - g.mean())))
        yy, xx = np.mgrid[-128:128, -128:128]
        rr = np.sqrt(xx ** 2 + yy ** 2)
        hf = float(spec[(rr > 60) & (rr < 120)].sum() / (spec[(rr > 5) & (rr < 120)].sum() + 1e-6))
        sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
        sat = float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1].std())
        draw_face(out, fc, "face")
        ctx.stat("High-frequency energy", round(hf, 3), "warn" if hf > 0.2 else None)
        ctx.stat("Sharpness", round(sharp), "warn" if sharp < 60 else None)
        ctx.stat("Color spread", round(sat, 1), "warn" if sat < 18 else None)
        ctx.note("These cues are not a decision. Train a YOLO26 classifier on live vs. spoof face crops "
                 "(e.g. the CelebA-Spoof dataset or your own captures), upload it, and pick it in Model.")
    ctx.add_image(out, "Face")
    ctx.add_image(crop, "Face crop sent to the classifier")


# ------------------------------------------------------------------ attendance / occupancy

@pipeline("attendance", "Classroom occupancy and attendance",
          "Counts people and occupied seats. Optionally matches faces against a roster of consenting students.",
          [Slot("media", "Classroom image or video", "media"),
           Slot("roster", "Roster photos (file name = person's name, optional)", "images", 0, 60, optional=True)],
          [Param("seats", "Seats", "polygons", [], help="Optional: outline each seat."),
           Param("threshold", "Face match threshold", "number", 0.4, 0.25, 0.7, 0.01, advanced=True), CONF, STRIDE],
          models=["yolo26-detect", "yunet", "sface"])
def attendance(ctx):
    roster = []
    for name, img in ctx.images("roster"):
        fs = detect_faces(img)
        if fs:
            feat, _ = face_feature(img, fs[0])
            roster.append((name.rsplit(".", 1)[0].replace("_", " "), feat))
    thr = float(ctx.p("threshold", 0.4))

    def fn(img, t, st):
        h, w = img.shape[:2]
        seats = polygons_param(ctx.p("seats"), w, h)
        people = [d for d in boxes_of(ctx.predict("yolo26-detect", img, conf=float(ctx.p("conf", 0.3)))[0]) if d["cls"] == "person"]
        out = img.copy()
        taken = []
        for i, s in enumerate(seats):
            occ = any(point_in_poly(center(p["box"]), s) for p in people)
            taken.append(occ)
            draw_poly(out, s, BLUE if occ else (160, 160, 160), 0.2)
        for p in people:
            box(out, p["box"], None, AMBER)
        present = st.setdefault("present", {})
        if roster:
            rec = None
            for fc in detect_faces(img):
                feat, rec = face_feature(img, fc)
                best = max(((rec.match(feat, rf, cv2.FaceRecognizerSF_FR_COSINE), nm) for nm, rf in roster), default=(0, None))
                if best[0] >= thr:
                    present[best[1]] = max(present.get(best[1], 0), round(float(best[0]), 3))
                    draw_face(out, fc, best[1], GREEN)
                else:
                    draw_face(out, fc, "unknown", (150, 150, 150))
        st["people"] = max(st.get("people", 0), len(people))
        st["taken"] = taken
        st.setdefault("t", []).append(round(t, 1))
        st.setdefault("n", []).append(len(people))
        banner(out, [f"People: {len(people)}"] + ([f"Seats taken: {sum(taken)}/{len(taken)}"] if seats else []))
        return out

    st = run_media(ctx, fn, slot="media", caption="Occupancy")
    ctx.stat("People" if not st.get("video") else "Peak people", st["people"])
    if st.get("taken"):
        ctx.stat("Seats taken", f"{sum(st['taken'])}/{len(st['taken'])}")
    if roster:
        names = [n for n, _ in roster]
        ctx.stat("Present", f"{len(st['present'])}/{len(names)}", "good")
        ctx.table("Attendance", ["Name", "Status", "Match score"],
                  [[n, "present" if n in st["present"] else "not seen", st["present"].get(n)] for n in names], "attendance.csv")
        ctx.note("Face matching is opt-in: only use roster photos of people who agreed to it.")
    if st.get("video"):
        ctx.chart("line", "People over time", st["t"], [{"name": "People", "values": st["n"]}], "Time (s)")


# ------------------------------------------------------------------ virtual try-on (2D)

@pipeline("virtual_tryon", "Virtual try-on (2D overlay)",
          "Warps a garment photo onto the person's torso using YOLO26 pose keypoints. Use a garment on a plain white background.",
          [Slot("person", "Person photo (facing the camera)"), Slot("garment", "Garment photo (plain background)")],
          [Param("width", "Garment width (× shoulders)", "number", 1.5, 1.0, 2.5, 0.05),
           Param("length", "Garment length (× torso)", "number", 1.15, 0.8, 2.0, 0.05)],
          models=["yolo26-pose"])
def virtual_tryon(ctx):
    person, garment = ctx.image("person"), ctx.image("garment")
    p = largest(pose_predict(ctx, person, 0.3))
    if p is None or not all(p["ok"][j] for j in (LSH, RSH, LHIP, RHIP)):
        raise UserError("Couldn't see both shoulders and hips. Use a front-facing, full-torso photo.")
    # garment mask: everything that differs from the border color
    g = garment.copy()
    border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]]).astype(np.float32)
    bg = np.median(border, axis=0)
    diff = np.linalg.norm(g.astype(np.float32) - bg, axis=2)
    mask = (diff > 28).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise UserError("Couldn't separate the garment from its background. Use a plain, light background.")
    big = max(cnts, key=cv2.contourArea)
    mask = np.zeros_like(mask)
    cv2.drawContours(mask, [big], -1, 255, -1)
    x, y, w, h = cv2.boundingRect(big)
    k = p["kp"]
    # image-left shoulder is the person's right shoulder
    sl, sr = (k[RSH], k[LSH]) if k[RSH][0] < k[LSH][0] else (k[LSH], k[RSH])
    hl, hr = (k[RHIP], k[LHIP]) if k[RHIP][0] < k[LHIP][0] else (k[LHIP], k[RHIP])
    sw = np.linalg.norm(sr - sl)
    torso = np.linalg.norm((hl + hr) / 2 - (sl + sr) / 2)
    ex = float(ctx.p("width", 1.5))
    ln = float(ctx.p("length", 1.15))
    dir_x = (sr - sl) / (sw + 1e-6)
    dir_y = ((hl + hr) / 2 - (sl + sr) / 2) / (torso + 1e-6)
    top_c = (sl + sr) / 2 - dir_y * torso * 0.12
    half = dir_x * sw * ex / 2
    dst = np.float32([top_c - half, top_c + half, top_c + half + dir_y * torso * ln, top_c - half + dir_y * torso * ln])
    src = np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
    M = cv2.getPerspectiveTransform(src, dst)
    H, W = person.shape[:2]
    warped = cv2.warpPerspective(g, M, (W, H))
    wm = cv2.warpPerspective(mask, M, (W, H)).astype(np.float32) / 255
    wm = cv2.GaussianBlur(wm, (5, 5), 0)[..., None]
    out = (person * (1 - wm) + warped * wm).astype(np.uint8)
    ctx.add_image(out, "Try-on preview")
    side = person.copy()
    draw_skeleton(side, p)
    ctx.add_image(side, "Pose used for fitting")
    ctx.stat("Shoulder width", round(float(sw)), unit="px")
    ctx.note("A 2D overlay for quick previews. Realistic draping needs a diffusion try-on model (e.g. IDM-VTON) on a GPU.")


# ------------------------------------------------------------------ driver attention

@pipeline("driver_attention", "Driver attention monitoring",
          "Tracks the driver's head direction from face landmarks and alerts when they look away or down for too long.",
          MEDIA, [Param("yaw", "Looking sideways if turn above", "number", 0.35, 0.1, 1.0, 0.05),
                  Param("down", "Looking down if pitch above", "number", 0.78, 0.5, 1.2, 0.02),
                  Param("seconds", "Alert after distracted for (s)", "number", 2.0, 0.5, 10, 0.5), STRIDE],
          models=["yunet"])
def driver_attention(ctx):
    yaw_t, down_t, hold = float(ctx.p("yaw", 0.35)), float(ctx.p("down", 0.78)), float(ctx.p("seconds", 2.0))

    def fn(img, t, st):
        faces = detect_faces(img, 0.5)
        out = img.copy()
        if not faces:
            state, detail = "face not visible", ""
        else:
            yaw, pitch, roll = head_pose(faces[0])
            state = "looking left" if yaw < -yaw_t else "looking right" if yaw > yaw_t else \
                    "looking down" if pitch > down_t else "looking up" if pitch < 0.3 else "attentive"
            detail = f"turn {yaw:+.2f} · pitch {pitch:.2f}"
            draw_face(out, faces[0], state, GREEN if state == "attentive" else RED)
        distracted = state != "attentive"
        if distracted:
            st["since"] = st.get("since") if st.get("since") is not None else t
        else:
            st["since"], st["alerted"] = None, False
        dur = 0 if st.get("since") is None else t - st["since"]
        if st.get("video") and distracted and dur >= hold and not st.get("alerted"):
            st["alerted"] = True
            st.setdefault("alerts", []).append([round(st["since"], 1), state])
        st["n"] = st.get("n", 0) + 1
        st["att"] = st.get("att", 0) + (not distracted)
        st["state"] = state
        st.setdefault("t", []).append(round(t, 2))
        st.setdefault("a", []).append(0 if distracted else 1)
        alarm = st.get("video") and distracted and dur >= hold
        banner(out, [f"State: {state}", detail or " ", "ALERT: eyes on the road" if alarm else " "],
               (40, 40, 170) if alarm else (30, 30, 30))
        return out

    st = run_media(ctx, fn, caption="Driver attention")
    if st.get("video"):
        ctx.stat("Attentive", round(st["att"] / max(1, st["n"]) * 100), "good" if st["att"] / max(1, st["n"]) > 0.8 else "bad", "%")
        ctx.stat("Alerts", len(st.get("alerts", [])), "bad" if st.get("alerts") else "good")
        ctx.chart("line", "Attention (1 = attentive)", st["t"], [{"name": "Attentive", "values": st["a"]}], "Time (s)")
        if st.get("alerts"):
            ctx.table("Alerts", ["Start (s)", "State"], st["alerts"], "driver_alerts.csv")
    else:
        ctx.stat("State", st["state"], "good" if st["state"] == "attentive" else "bad")
    ctx.note("Head direction from 5 face landmarks. Eye-closure (drowsiness) detection needs a dense face-mesh model such as MediaPipe; "
             "add an infrared camera for night driving.")
