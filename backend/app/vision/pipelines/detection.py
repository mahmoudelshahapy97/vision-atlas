"""YOLO26 detection, segmentation, OBB, classification, YOLOE-26 open vocabulary, and detection-based apps."""
from __future__ import annotations

import json
import re

import cv2
import numpy as np

from ..core import (CONF, COCO, DET_COLS, GREEN, IMAGE, IMGSZ, MEDIA, RED, STRIDE, VEHICLES, AMBER, Param, Slot,
                    UserError, banner, box, boxes_of, center, classes_param, color_for, counts, det_rows, draw_poly,
                    iou, label, masks_of, pipeline, point_in_poly, polygons_param)
from ..registry import ModelError
from .common import draw_dets, filter_classes, mask_area_pct, prompts_list, run_media, dominant_color


def _counts_summary(ctx, st: dict, word: str = "Objects") -> None:
    if st.get("video"):
        peak = st.get("peak", {})
        ctx.stat(f"Peak {word.lower()} in one frame", sum(peak.values()) if peak else 0)
        if peak:
            ctx.table("Peak count per class (single frame)", ["Class", "Peak count"], [[k, v] for k, v in peak.items()])
            ctx.chart("line", f"{word} per frame", st.get("t", []), [{"name": word, "values": st.get("n", [])}],
                      "Time (s)", "Count")
    else:
        dets = st.get("dets", [])
        ctx.stat(word, len(dets))
        for k, v in list(counts(dets).items())[:5]:
            ctx.stat(k, v)
        if dets:
            ctx.table("Detections", DET_COLS, det_rows(dets), "detections.csv")


def _track_peaks(st: dict, dets: list[dict], t: float) -> None:
    c = counts(dets)
    peak = st.setdefault("peak", {})
    for k, v in c.items():
        peak[k] = max(peak.get(k, 0), v)
    st.setdefault("t", []).append(round(t, 2))
    st.setdefault("n", []).append(len(dets))
    st["dets"] = dets


# ------------------------------------------------------------------ YOLO26 detect

@pipeline("detect", "YOLO26 object detection",
          "Finds and labels objects with the official YOLO26 model (80 COCO classes) or your own trained weights.",
          MEDIA, [classes_param(), CONF, IMGSZ, STRIDE], models=["yolo26-detect"], custom_task="detect")
def detect(ctx):
    key = ctx.model_key("yolo26-detect")
    names = ctx.p("classes", [])

    def fn(img, t, st):
        r = ctx.predict(key, img, conf=float(ctx.p("conf", 0.25)), imgsz=int(ctx.p("imgsz", 640)))[0]
        dets = filter_classes(boxes_of(r), names)
        _track_peaks(st, dets, t)
        return draw_dets(img, dets)

    st = run_media(ctx, fn, caption="Detections")
    _counts_summary(ctx, st)


# ------------------------------------------------------------------ YOLOE-26 open vocabulary

@pipeline("open_vocab", "YOLOE-26 open-vocabulary detection",
          "Type what to look for and YOLOE-26 detects and segments it with no training. "
          "Good for a first prototype; fine-tune YOLO26 on your own data for production accuracy.",
          MEDIA, [Param("prompts", "What to look for", "text", "person, car",
                        help="Comma-separated, in English, e.g. 'pothole, road crack'."),
                  Param("conf", "Confidence threshold", "number", 0.2, 0.05, 0.9, 0.05),
                  Param("masks", "Show masks", "bool", True), IMGSZ, STRIDE],
          models=["yoloe26"])
def open_vocab(ctx):
    prompts = prompts_list(ctx.p("prompts"))
    show_masks = bool(ctx.p("masks", True))

    def fn(img, t, st):
        r = ctx.yoloe(prompts, img, conf=float(ctx.p("conf", 0.2)), imgsz=int(ctx.p("imgsz", 640)))[0]
        dets = boxes_of(r)
        masks = masks_of(r, img.shape) if show_masks else None
        if not st.get("video") and masks:
            st["areas"] = {d["i"]: mask_area_pct(masks[d["i"]]) for d in dets if d["i"] < len(masks)}
        _track_peaks(st, dets, t)
        return draw_dets(img, dets, masks)

    st = run_media(ctx, fn, caption="Open-vocabulary detections")
    _counts_summary(ctx, st)
    if not st.get("video"):
        found = counts(st.get("dets", []))
        missing = [p for p in prompts if p not in found]
        if missing:
            ctx.note(f"Nothing found for: {', '.join(missing)}. Try a lower confidence or a different word.")
    ctx.note("Zero-shot results. For reliable accuracy, label ~200+ images and fine-tune YOLO26, then upload the weights.")


# ------------------------------------------------------------------ YOLO26 segment

@pipeline("segment", "YOLO26 instance segmentation",
          "Outlines each object with a pixel mask and measures its area.",
          MEDIA, [classes_param(), CONF, IMGSZ, STRIDE], models=["yolo26-segment"], custom_task="segment")
def segment(ctx):
    key = ctx.model_key("yolo26-segment")
    names = ctx.p("classes", [])

    def fn(img, t, st):
        r = ctx.predict(key, img, conf=float(ctx.p("conf", 0.25)), imgsz=int(ctx.p("imgsz", 640)))[0]
        dets = filter_classes(boxes_of(r), names)
        masks = masks_of(r, img.shape)
        if not st.get("video"):
            st["rows"] = [[d["cls"], round(d["conf"], 3), int(masks[d["i"]].sum()), round(mask_area_pct(masks[d["i"]]), 2)]
                          for d in dets if d["i"] < len(masks)]
            st["polys"] = [{"class": d["cls"], "confidence": round(d["conf"], 3),
                            "polygon": r.masks.xy[d["i"]].round(1).tolist()} for d in dets if r.masks is not None]
        _track_peaks(st, dets, t)
        return draw_dets(img, dets, masks)

    st = run_media(ctx, fn, caption="Segmentation")
    if st.get("video"):
        _counts_summary(ctx, st)
        return
    ctx.stat("Instances", len(st.get("rows", [])))
    if st.get("rows"):
        ctx.stat("Total mask area", round(sum(r[3] for r in st["rows"]), 1), unit="% of image")
        ctx.table("Instances", ["Class", "Confidence", "Area (px)", "Area (% of image)"], st["rows"], "instances.csv")
        ctx.add_json(st["polys"], "polygons.json")


# ------------------------------------------------------------------ YOLO26 OBB (aerial)

@pipeline("obb", "YOLO26 oriented boxes (aerial)",
          "Detects planes, ships, vehicles, storage tanks and more in aerial or satellite images with rotated boxes.",
          IMAGE, [Param("conf", "Confidence threshold", "number", 0.25, 0.05, 0.95, 0.05),
                  Param("imgsz", "Inference size (px)", "select", 1024, options=[640, 1024, 1280])],
          models=["yolo26-obb"], custom_task="obb")
def obb(ctx):
    img = ctx.image()
    r = ctx.predict(ctx.model_key("yolo26-obb"), img, conf=float(ctx.p("conf", 0.25)), imgsz=int(ctx.p("imgsz", 1024)))[0]
    out = img.copy()
    rows = []
    if r.obb is not None and len(r.obb):
        pts = r.obb.xyxyxyxy.cpu().numpy().astype(np.int32)
        cls = r.obb.cls.cpu().numpy().astype(int)
        conf = r.obb.conf.cpu().numpy()
        xywhr = r.obb.xywhr.cpu().numpy()
        for p, c, s, (x, y, w, h, a) in zip(pts, cls, conf, xywhr):
            name = r.names[c]
            draw_poly(out, p, color_for(name))
            label(out, f"{name} {s:.2f}", int(p[:, 0].min()), int(p[:, 1].min()), color_for(name))
            rows.append([name, round(float(s), 3), round(float(x)), round(float(y)), round(float(w)), round(float(h)),
                         round(float(np.degrees(a)), 1)])
    ctx.add_image(out, "Oriented detections")
    ctx.stat("Objects", len(rows))
    c: dict[str, int] = {}
    for row in rows:
        c[row[0]] = c.get(row[0], 0) + 1
    for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:5]:
        ctx.stat(k, v)
    if rows:
        ctx.table("Objects", ["Class", "Confidence", "Center x", "Center y", "Width", "Height", "Angle (°)"], rows, "obb.csv")
    else:
        ctx.note("Nothing found. This model expects top-down aerial imagery (DOTA classes).")


# ------------------------------------------------------------------ YOLO26 classify

@pipeline("classify", "YOLO26 image classification",
          "Top-5 labels for each image from YOLO26 (1000 ImageNet classes) or your own trained classifier.",
          [Slot("images", "Images", "images", 1, 30)],
          [Param("topk", "Labels per image", "int", 5, 1, 10), Param("focus", "Only show labels containing", "text", "",
                                                                     help="Optional keywords, e.g. 'shoe, boot, sandal'.")],
          models=["yolo26-classify"], custom_task="classify")
def classify(ctx):
    key = ctx.model_key("yolo26-classify")
    k = int(ctx.p("topk", 5))
    focus = [w.lower() for w in prompts_list(ctx.p("focus"))]
    imgs = ctx.images("images")
    if not imgs:
        raise UserError("Add at least one image.")
    rows, first = [], None
    for n, (name, img) in enumerate(imgs):
        r = ctx.predict(key, img)[0]
        probs = r.probs.data.cpu().numpy()
        order = np.argsort(-probs)
        labels = [(r.names[int(i)], float(probs[i])) for i in order]
        if focus:
            labels = [x for x in labels if any(w in x[0].lower() for w in focus)] or labels
        labels = labels[:k]
        rows.append([name, labels[0][0], round(labels[0][1], 3), ", ".join(f"{a} ({b:.2f})" for a, b in labels[1:])])
        if n < 6:
            out = img.copy()
            banner(out, [f"{a}: {b:.0%}" for a, b in labels[:3]])
            ctx.add_image(out, name)
        if first is None:
            first = labels
        ctx.progress((n + 1) / len(imgs))
    ctx.stat("Images", len(imgs))
    ctx.stat("Top label", rows[0][1])
    ctx.stat("Confidence", rows[0][2])
    ctx.table("Predictions", ["Image", "Top label", "Confidence", "Other labels"], rows, "predictions.csv")
    ctx.chart("bar", f"Top {k} for {imgs[0][0]}", [a for a, _ in first], [{"name": "Probability", "values": [round(b, 4) for _, b in first]}])
    if key == "yolo26-classify":
        ctx.note("ImageNet labels are general-purpose. Train a YOLO26 classifier on your own classes and upload it for domain-specific results.")


# ------------------------------------------------------------------ self-checkout

DEFAULT_PRICES = "apple = 0.60\nbanana = 0.30\norange = 0.75\nbottle = 1.50\ncup = 2.00\nsandwich = 4.50\ndonut = 1.25\ncake = 3.00\nbroccoli = 1.10\ncarrot = 0.40"


def parse_prices(text: str) -> dict[str, float]:
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([^=:]+?)\s*[=:]\s*([\d.,]+)", line)
        if m:
            out[m.group(1).strip().lower()] = float(m.group(2).replace(",", "."))
    return out


@pipeline("checkout", "Visual self-checkout",
          "Recognizes products at the checkout and adds up the basket from your price list.",
          IMAGE, [Param("prices", "Price list (item = price)", "textarea", DEFAULT_PRICES,
                        help="Item names must match the model's class names."),
                  Param("currency", "Currency", "text", "SAR"), CONF],
          models=["yolo26-detect"], custom_task="detect")
def checkout(ctx):
    img = ctx.image()
    prices = parse_prices(ctx.p("prices", DEFAULT_PRICES))
    cur = ctx.p("currency", "SAR")
    r = ctx.predict(ctx.model_key("yolo26-detect"), img, conf=float(ctx.p("conf", 0.25)))[0]
    dets = [d for d in boxes_of(r) if d["cls"].lower() in prices]
    ignored = [d for d in boxes_of(r) if d["cls"].lower() not in prices]
    out = draw_dets(img, dets, text_fn=lambda d: f"{d['cls']} {prices[d['cls'].lower()]:.2f}")
    c = counts(dets)
    rows = [[k, v, prices[k.lower()], round(v * prices[k.lower()], 2)] for k, v in c.items()]
    total = round(sum(r[3] for r in rows), 2)
    banner(out, [f"Items: {len(dets)}", f"Total: {total:.2f} {cur}"])
    ctx.add_image(out, "Basket")
    ctx.stat("Items", len(dets))
    ctx.stat("Total", f"{total:.2f} {cur}")
    ctx.table("Receipt", ["Item", "Qty", f"Unit price ({cur})", f"Line total ({cur})"], rows, "receipt.csv")
    if ignored:
        ctx.note(f"Seen but not in the price list: {', '.join(sorted({d['cls'] for d in ignored}))}.")
    ctx.note("COCO only covers a few grocery items. Train YOLO26 on your own product photos for a real store.")


# ------------------------------------------------------------------ helmet check (motorcycle riders)

@pipeline("helmet_check", "Helmet detection for riders",
          "Finds motorcycle and bicycle riders with YOLO26, then checks each rider's head for a helmet with YOLOE-26.",
          MEDIA, [Param("riders_only", "Only check riders on two-wheelers", "bool", True),
                  Param("conf", "Person/vehicle confidence", "number", 0.3, 0.1, 0.9, 0.05),
                  Param("helmet_conf", "Helmet confidence", "number", 0.15, 0.05, 0.9, 0.05), STRIDE],
          models=["yolo26-detect", "yoloe26"])
def helmet_check(ctx):
    riders_only = bool(ctx.p("riders_only", True))

    def fn(img, t, st):
        dets = boxes_of(ctx.predict("yolo26-detect", img, conf=float(ctx.p("conf", 0.3)))[0])
        people = [d for d in dets if d["cls"] == "person"]
        bikes = [d for d in dets if d["cls"] in ("motorcycle", "bicycle")]
        if riders_only:
            people = [p for p in people if any(_rides(p["box"], b["box"]) for b in bikes)]
        helmets = boxes_of(ctx.yoloe(["helmet"], img, conf=float(ctx.p("helmet_conf", 0.15)))[0])
        out = img.copy()
        for b in bikes:
            box(out, b["box"], b["cls"], (150, 150, 150), 1)
        ok = bad = 0
        for p in people:
            x1, y1, x2, y2 = p["box"]
            head = [x1, y1 - 0.1 * (y2 - y1), x2, y1 + 0.35 * (y2 - y1)]
            has = any(_inside(center(h["box"]), head) for h in helmets)
            ok, bad = ok + has, bad + (not has)
            box(out, p["box"], "helmet" if has else "NO HELMET", GREEN if has else RED)
        for h in helmets:
            box(out, h["box"], None, AMBER, 1)
        st["ok"], st["bad"] = st.get("ok", 0) + ok, st.get("bad", 0) + bad
        st["max_bad"] = max(st.get("max_bad", 0), bad)
        st.setdefault("t", []).append(round(t, 2))
        st.setdefault("v", []).append(bad)
        banner(out, [f"Riders: {ok + bad}", f"With helmet: {ok}", f"Without: {bad}"])
        return out

    st = run_media(ctx, fn, caption="Helmet check")
    if st.get("video"):
        ctx.stat("Most violations in one frame", st.get("max_bad", 0), "bad" if st.get("max_bad") else "good")
        ctx.chart("line", "Riders without helmet", st["t"], [{"name": "Without helmet", "values": st["v"]}], "Time (s)")
    else:
        ctx.stat("Riders", st["ok"] + st["bad"])
        ctx.stat("With helmet", st["ok"], "good")
        ctx.stat("Without helmet", st["bad"], "bad" if st["bad"] else "good")
    ctx.note("Helmets are found zero-shot with YOLOE-26. Fine-tune YOLO26 on rider images for enforcement use; a person should review every flagged case.")


def _rides(p, b) -> bool:
    px, py = center(p)
    return b[0] - 0.2 * (b[2] - b[0]) <= px <= b[2] + 0.2 * (b[2] - b[0]) and p[3] >= b[1] and p[1] <= b[1] + 0.3 * (b[3] - b[1]) and iou(p, b) > 0.05


def _inside(pt, b) -> bool:
    return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


# ------------------------------------------------------------------ PPE compliance

PPE_ITEMS = {"helmet": (["hardhat", "helmet", "hard hat"], ["no-hardhat"]),
             "vest": (["safety vest", "vest"], ["no-safety vest"]),
             "mask": (["mask"], ["no-mask"]),
             "gloves": (["gloves"], ["no-gloves"]),
             "goggles": (["goggles"], ["no-goggles"])}


@pipeline("ppe_compliance", "PPE compliance check",
          "Checks each worker for the protective equipment you require. Uses a public PPE model when available, otherwise YOLOE-26 prompts.",
          MEDIA, [Param("required", "Required equipment", "multiselect", ["helmet", "vest"], options=list(PPE_ITEMS)),
                  Param("conf", "Confidence threshold", "number", 0.3, 0.05, 0.9, 0.05), STRIDE],
          models=["ppe-yolov8", "yoloe26", "yolo26-detect"], custom_task="detect")
def ppe_compliance(ctx):
    required = ctx.p("required", ["helmet", "vest"]) or ["helmet", "vest"]
    conf = float(ctx.p("conf", 0.3))
    key = ctx.model_key("ppe-yolov8")
    mode = {"key": key}
    try:
        from ..registry import manager
        manager.get(key)
    except ModelError as e:
        mode["key"] = None
        ctx.note(f"Public PPE model unavailable ({e}). Using YOLOE-26 zero-shot prompts instead.")

    def detect_all(img):
        if mode["key"]:
            dets = boxes_of(ctx.predict(mode["key"], img, conf=conf)[0])
            people = [d for d in dets if d["cls"].lower() == "person"]
            if not people:
                people = [d for d in boxes_of(ctx.predict("yolo26-detect", img, conf=conf)[0]) if d["cls"] == "person"]
            return people, [d for d in dets if d["cls"].lower() != "person"]
        people = [d for d in boxes_of(ctx.predict("yolo26-detect", img, conf=conf)[0]) if d["cls"] == "person"]
        prompts = {"helmet": "hard hat", "vest": "safety vest", "mask": "face mask", "gloves": "gloves", "goggles": "safety goggles"}
        gear = boxes_of(ctx.yoloe([prompts[r] for r in required], img, conf=max(0.1, conf - 0.15))[0])
        return people, gear

    def fn(img, t, st):
        people, gear = detect_all(img)
        out, checks = ppe_frame(img, people, gear, required)
        rows = [[i + 1, "compliant" if ok else "violation", ", ".join(missing) or "none"] for i, (_, ok, missing) in enumerate(checks)]
        ok_n = sum(ok for _, ok, _ in checks)
        st["rows"], st["ok"], st["n"] = rows, ok_n, len(people)
        st["worst"] = max(st.get("worst", 0), len(people) - ok_n)
        return out

    st = run_media(ctx, fn, caption="PPE compliance")
    if st.get("video"):
        ctx.stat("Most violations in one frame", st.get("worst", 0), "bad" if st.get("worst") else "good")
    else:
        ctx.stat("Workers", st["n"])
        ctx.stat("Compliant", st["ok"], "good")
        ctx.stat("Violations", st["n"] - st["ok"], "bad" if st["n"] - st["ok"] else "good")
        if st["rows"]:
            ctx.table("Workers", ["#", "Status", "Missing"], st["rows"], "ppe.csv")


def ppe_frame(img, people: list[dict], gear: list[dict], required: list[str]):
    """Checks each person for the required equipment near them and draws the
    result. Shared by the lab pipeline and its live camera analyzer. Returns
    (annotated, [(person, compliant, missing items)])."""
    out = img.copy()
    checks = []
    for p in people:
        x1, y1, x2, y2 = p["box"]
        expanded = [x1 - 0.1 * (x2 - x1), y1 - 0.15 * (y2 - y1), x2 + 0.1 * (x2 - x1), y2]
        status = {}
        for item in required:
            pos, neg = PPE_ITEMS[item]
            near = [g for g in gear if _inside(center(g["box"]), expanded)]
            if any(g["cls"].lower() in neg for g in near):
                status[item] = False
            else:
                status[item] = any(any(w in g["cls"].lower() for w in pos) and g["cls"].lower() not in neg for g in near)
        ok = all(status.values())
        missing = [k for k, v in status.items() if not v]
        box(out, p["box"], "OK" if ok else "missing: " + ", ".join(missing), GREEN if ok else RED)
        checks.append((p, ok, missing))
    for g in gear:
        box(out, g["box"], g["cls"], color_for(g["cls"]), 1)
    ok_n = sum(ok for _, ok, _ in checks)
    banner(out, [f"Workers: {len(people)}", f"Compliant: {ok_n}", f"Violations: {len(people) - ok_n}"])
    return out, checks


# ------------------------------------------------------------------ parking occupancy

@pipeline("parking_occupancy", "Parking occupancy",
          "Counts vehicles and, if you draw parking spaces, marks each space free or occupied.",
          MEDIA, [Param("slots", "Parking spaces", "polygons", [], help="Draw one polygon per space on the image."),
                  Param("conf", "Confidence threshold", "number", 0.3, 0.05, 0.9, 0.05), STRIDE],
          models=["yolo26-detect"], custom_task="detect")
def parking_occupancy(ctx):
    def fn(img, t, st):
        dets = boxes_of(ctx.predict(ctx.model_key("yolo26-detect"), img, conf=float(ctx.p("conf", 0.3)))[0])
        out, vehicles, occ = parking_frame(img, dets, ctx.p("slots"))
        st["vehicles"], st["occ"] = vehicles, occ
        st.setdefault("t", []).append(round(t, 2))
        st.setdefault("free", []).append(len(occ) - sum(occ))
        return out

    st = run_media(ctx, fn, caption="Parking occupancy")
    ctx.stat("Vehicles", st["vehicles"])
    if st["occ"]:
        ctx.stat("Occupied", sum(st["occ"]), "bad")
        ctx.stat("Free", len(st["occ"]) - sum(st["occ"]), "good")
        ctx.stat("Occupancy", round(sum(st["occ"]) / len(st["occ"]) * 100), unit="%")
        ctx.table("Spaces", ["Space", "Status"], [[f"P{i + 1}", "occupied" if o else "free"] for i, o in enumerate(st["occ"])], "spaces.csv")
        if st.get("video"):
            ctx.chart("line", "Free spaces over time", st["t"], [{"name": "Free", "values": st["free"]}], "Time (s)")
    else:
        ctx.note("Draw parking spaces on the image to get per-space occupancy.")


def parking_frame(img, dets: list[dict], slots_param):
    """Marks each drawn space free or occupied by the vehicles detected.
    Shared by the lab pipeline and its live camera analyzer. Returns
    (annotated, vehicle count, [occupied per space])."""
    h, w = img.shape[:2]
    slots = polygons_param(slots_param, w, h)
    dets = [d for d in dets if d["cls"] in ("car", "truck", "bus", "motorcycle")]
    out = img.copy()
    occ = []
    for i, poly in enumerate(slots):
        pm = np.zeros((h, w), np.uint8)
        cv2.fillPoly(pm, [poly], 1)
        area = max(1, int(pm.sum()))
        taken = False
        for d in dets:
            x1, y1, x2, y2 = map(int, d["box"])
            inter = int(pm[max(0, y1):y2, max(0, x1):x2].sum())
            if inter / area > 0.3 or point_in_poly(((x1 + x2) / 2, y2 - 0.15 * (y2 - y1)), poly):
                taken = True
                break
        occ.append(taken)
        draw_poly(out, poly, RED if taken else GREEN, 0.25)
        label(out, f"P{i + 1}", int(poly[:, 0].mean()), int(poly[:, 1].mean()), RED if taken else GREEN, (255, 255, 255))
    for d in dets:
        box(out, d["box"], None, AMBER, 1)
    lines = [f"Vehicles: {len(dets)}"]
    if slots:
        lines += [f"Occupied: {sum(occ)}/{len(occ)}", f"Free: {len(occ) - sum(occ)}"]
    banner(out, lines)
    return out, len(dets), occ


# ------------------------------------------------------------------ clothing parsing

@pipeline("clothing_parsing", "Clothing detection and colors",
          "Finds garments and accessories with YOLOE-26 and names each item's main color.",
          IMAGE, [Param("prompts", "Items", "text", "suit, coat, jacket, shirt, t-shirt, tie, pants, jeans, skirt, dress, shoe, bag, hat"),
                  Param("conf", "Confidence threshold", "number", 0.2, 0.05, 0.9, 0.05)],
          models=["yoloe26"])
def clothing_parsing(ctx):
    img = ctx.image()
    r = ctx.yoloe(prompts_list(ctx.p("prompts")), img, conf=float(ctx.p("conf", 0.2)))[0]
    dets = boxes_of(r)
    masks = masks_of(r, img.shape)
    rows = []
    for d in dets:
        m = masks[d["i"]] if d["i"] < len(masks) else None
        name, _ = dominant_color(img, m)
        d["color"] = name
        rows.append([d["cls"], name, round(d["conf"], 2), round(mask_area_pct(m), 1) if m is not None else None])
    out = draw_dets(img, dets, masks, text_fn=lambda d: f"{d['color']} {d['cls']}")
    ctx.add_image(out, "Garments")
    ctx.stat("Items", len(dets))
    ctx.table("Items", ["Item", "Color", "Confidence", "Area %"], rows, "garments.csv")


# ------------------------------------------------------------------ waste sorting

WASTE_MAP = {"plastic bottle": "plastic", "plastic bag": "plastic", "plastic cup": "plastic", "paper": "paper",
             "cardboard box": "paper", "newspaper": "paper", "glass bottle": "glass", "glass jar": "glass",
             "aluminum can": "metal", "metal can": "metal", "food waste": "organic", "banana peel": "organic"}


@pipeline("waste_sorting", "Waste sorting",
          "Detects waste items with YOLOE-26 and groups them into recycling streams.",
          MEDIA, [Param("mapping", "Item → stream", "textarea", "\n".join(f"{k} = {v}" for k, v in WASTE_MAP.items())),
                  Param("conf", "Confidence threshold", "number", 0.2, 0.05, 0.9, 0.05), STRIDE],
          models=["yoloe26"])
def waste_sorting(ctx):
    mapping = {}
    for line in (ctx.p("mapping") or "").splitlines():
        if "=" in line:
            a, b = line.split("=", 1)
            mapping[a.strip().lower()] = b.strip().lower()
    mapping = mapping or WASTE_MAP
    streams = sorted(set(mapping.values()))
    scol = {s: color_for(s) for s in streams}

    def fn(img, t, st):
        r = ctx.yoloe(list(mapping), img, conf=float(ctx.p("conf", 0.2)))[0]
        dets = boxes_of(r)
        for d in dets:
            d["stream"] = mapping.get(d["cls"].lower(), "other")
        _track_peaks(st, dets, t)
        out = draw_dets(img, dets, masks_of(r, img.shape), color_fn=lambda d: scol.get(d["stream"], (128, 128, 128)),
                        text_fn=lambda d: f"{d['stream']}: {d['cls']}")
        return out

    st = run_media(ctx, fn, caption="Waste streams")
    dets = st.get("dets", [])
    per = {}
    for d in dets:
        per[d["stream"]] = per.get(d["stream"], 0) + 1
    ctx.stat("Items", len(dets))
    for k, v in sorted(per.items(), key=lambda kv: -kv[1]):
        ctx.stat(k.capitalize(), v)
    if dets:
        ctx.table("Items", ["Item", "Stream", "Confidence"], [[d["cls"], d["stream"], round(d["conf"], 2)] for d in dets], "waste.csv")
    ctx.note("Zero-shot. For a sorting line, fine-tune YOLO26 on photos from your own conveyor.")
