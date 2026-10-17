"""Medical image preparation (X-ray, retina, skin), SAM promptable segmentation, and sign-language hand crops."""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import AMBER, BLUE, GREEN, IMAGE, MEDIA, RED, WHITE, Param, UserError, banner, box, fit, norm_points, pipeline
from .common import run_media, to_gray

MED_NOTE = ("Research and education only — not a diagnosis. Clinical use needs a validated model, appropriate datasets and "
            "review by a qualified clinician.")


def _custom_classify(ctx, img):
    key = ctx.params.get("model")
    if not (isinstance(key, str) and key.startswith("custom:")):
        return None
    r = ctx.predict(key, img)[0]
    probs = r.probs.data.cpu().numpy()
    order = np.argsort(-probs)[:5]
    rows = [[r.names[int(i)], round(float(probs[i]), 3)] for i in order]
    ctx.table("Your model's prediction", ["Class", "Probability"], rows)
    ctx.stat("Model says", rows[0][0])
    ctx.stat("Probability", rows[0][1])
    return rows


@pipeline("medical_classify", "Medical image analysis",
          "Prepares X-ray, retina or skin images with standard preprocessing, measures classical cues, and runs your trained classifier.",
          IMAGE, [Param("mode", "Image type", "select", "chest x-ray", options=["chest x-ray", "retina", "skin lesion"]),
                  Param("mm_per_px", "Skin: scale (mm per pixel)", "number", 0.05, 0.001, 5, 0.001, advanced=True)],
          models=[], custom_task="classify")
def medical_classify(ctx):
    img = fit(ctx.image(), 1600)
    mode = ctx.p("mode", "chest x-ray")
    g = to_gray(img)
    if mode == "chest x-ray":
        eq = cv2.createCLAHE(2.5, (8, 8)).apply(g)
        _, body = cv2.threshold(cv2.GaussianBlur(eq, (9, 9), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        inv = cv2.morphologyEx(255 - body, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, 8)
        H, W = g.shape
        lungs = [i for i in range(1, n) if stats[i][0] > 0 and stats[i][0] + stats[i][2] < W and stats[i][4] > 0.03 * g.size]
        lungs = sorted(lungs, key=lambda i: -stats[i][4])[:2]
        out = cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR)
        for i in lungs:
            cv2.drawContours(out, cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, GREEN, 3)
        ctx.add_image(out, "Contrast-enhanced (CLAHE) with approximate lung fields")
        ctx.stat("Lung fields found", len(lungs))
        if len(lungs) == 2:
            a1, a2 = stats[lungs[0]][4], stats[lungs[1]][4]
            ctx.stat("Left/right area ratio", round(min(a1, a2) / max(a1, a2), 2))
        model_in = cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR)
    elif mode == "retina":
        green = img[..., 1]
        fov = (cv2.GaussianBlur(to_gray(img), (15, 15), 0) > 20).astype(np.uint8)
        eq = cv2.createCLAHE(3.0, (8, 8)).apply(green)
        vessels = cv2.morphologyEx(eq, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        vmask = ((vessels > np.percentile(vessels[fov > 0], 90)) & (fov > 0)).astype(np.uint8)
        bright = cv2.morphologyEx(eq, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
        ex = ((bright > np.percentile(bright[fov > 0], 99.5)) & (fov > 0)).astype(np.uint8)
        dark = cv2.morphologyEx(eq, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        red_spots = ((dark > np.percentile(dark[fov > 0], 99.7)) & (vmask == 0) & (fov > 0)).astype(np.uint8)
        n_ex = cv2.connectedComponents(ex)[0] - 1
        n_red = cv2.connectedComponents(red_spots)[0] - 1
        out = img.copy()
        out[vmask > 0] = (out[vmask > 0] * 0.4 + np.array(BLUE) * 0.6).astype(np.uint8)
        out[cv2.dilate(ex, np.ones((5, 5), np.uint8)) > 0] = (60, 230, 255)
        out[cv2.dilate(red_spots, np.ones((5, 5), np.uint8)) > 0] = RED
        ctx.add_image(cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR), "Green channel, CLAHE (standard retinal preprocessing)")
        ctx.add_image(out, "Vessels (blue), bright lesions (yellow), dark spots (red)")
        ctx.stat("Vessel density", round(float(vmask.sum() / max(1, fov.sum()) * 100), 1), unit="%")
        ctx.stat("Bright lesion candidates", n_ex, "warn" if n_ex > 5 else None)
        ctx.stat("Dark spot candidates", n_red, "warn" if n_red > 5 else None)
        model_in = img
    else:  # skin lesion: DullRazor hair removal + ABCD
        bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17)))
        hair = (bh > 12).astype(np.uint8) * 255
        clean = cv2.inpaint(img, hair, 5, cv2.INPAINT_TELEA)
        gc = cv2.GaussianBlur(to_gray(clean), (7, 7), 0)
        _, les = cv2.threshold(gc, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(les, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        H, W = gc.shape
        cnts = [c for c in cnts if cv2.contourArea(c) > 0.01 * g.size]
        if not cnts:
            raise UserError("Couldn't outline the lesion. Center it in the photo on even skin with good light.")
        c = min(cnts, key=lambda c: np.hypot(*(np.array(cv2.minEnclosingCircle(c)[0]) - [W / 2, H / 2])))
        m = np.zeros_like(gc)
        cv2.drawContours(m, [c], -1, 1, -1)
        area, per = cv2.contourArea(c), cv2.arcLength(c, True)
        M = cv2.moments(c)
        cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
        _, (ma, MA), ang = cv2.fitEllipse(c) if len(c) >= 5 else ((0, 0), (1, 1), 0)
        rot = cv2.warpAffine(m, cv2.getRotationMatrix2D((cx, cy), ang, 1), (W, H))
        A_score = 0
        for flip in (0, 1):
            f = cv2.flip(rot, flip)
            sh = cv2.warpAffine(f, np.float32([[1, 0, (W - 2 * cx) if flip == 1 else 0], [0, 1, (H - 2 * cy) if flip == 0 else 0]]), (W, H))
            A_score += int((np.logical_xor(rot, sh).sum() / max(1, rot.sum())) > 0.15)
        compact = per ** 2 / (4 * math.pi * area)
        B_score = min(8, int(round((compact - 1) * 8)))
        hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
        px_hsv, px_bgr = hsv[m > 0], clean[m > 0]
        colors = {"white": (px_hsv[:, 2] > 200) & (px_hsv[:, 1] < 40), "black": px_hsv[:, 2] < 50,
                  "light brown": (px_hsv[:, 2] >= 120) & (px_hsv[:, 1] >= 40), "dark brown": (px_hsv[:, 2] >= 50) & (px_hsv[:, 2] < 120),
                  "red": ((px_hsv[:, 0] < 8) | (px_hsv[:, 0] > 170)) & (px_hsv[:, 1] > 120),
                  "blue-gray": (px_bgr[:, 0] > px_bgr[:, 2] + 10) & (px_hsv[:, 1] < 80)}
        present = [k for k, v in colors.items() if v.mean() > 0.05]
        C_score = len(present)
        diam_mm = max(ma, MA) * float(ctx.p("mm_per_px", 0.05))
        D_score = 5 if diam_mm > 6 else max(1, min(5, int(diam_mm)))
        tds = 1.3 * A_score + 0.1 * B_score + 0.5 * C_score + 0.5 * D_score
        band = "low" if tds < 4.75 else "intermediate" if tds <= 5.45 else "high"
        out = clean.copy()
        cv2.drawContours(out, [c], -1, GREEN, 3)
        banner(out, [f"TDS {tds:.2f} ({band})", f"A{A_score} B{B_score} C{C_score} D{D_score}"])
        ctx.add_image(out, "Hair removed (DullRazor) and lesion outline")
        ctx.stat("ABCD total score", round(tds, 2), "good" if band == "low" else "warn" if band == "intermediate" else "bad")
        ctx.stat("Score band", band)
        ctx.table("ABCD criteria", ["Criterion", "Value", "Score", "Weight"],
                  [["Asymmetry (axes)", A_score, A_score, 1.3], ["Border irregularity", round(compact, 2), B_score, 0.1],
                   ["Colors", ", ".join(present) or "—", C_score, 0.5], ["Diameter (mm)", round(diam_mm, 1), D_score, 0.5]])
        model_in = clean
    if _custom_classify(ctx, model_in) is None:
        ctx.note("Upload a YOLO26 classifier trained on your images (e.g. NIH ChestX-ray14, APTOS 2019, ISIC) and pick it in Model to get predictions.")
    ctx.note(MED_NOTE)


# ------------------------------------------------------------------ SAM

@pipeline("promptable_segmentation", "Promptable segmentation (SAM 2.1)",
          "Click on the object (green = include, right-click = exclude) or draw a box, and SAM 2.1 outlines it pixel-precisely.",
          IMAGE, [Param("points", "Points", "points", [], help="Click the object. Shift-click marks background."),
                  Param("box", "Box", "box", None)],
          models=["sam2"])
def promptable_segmentation(ctx):
    img = fit(ctx.image(), 1600)
    h, w = img.shape[:2]
    kw = {}
    pts = ctx.p("points") or []
    if pts:
        arr = np.asarray(pts, dtype=float).reshape(-1, 3)
        kw["points"] = [[[float(x * w), float(y * h)] for x, y, _ in arr]]
        kw["labels"] = [[int(l) for _, _, l in arr]]
    if ctx.p("box"):
        b = norm_points(ctx.p("box"), w, h)
        if len(b) >= 2:
            kw["bboxes"] = [[float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 0].max()), float(b[:, 1].max())]]
    if not kw:
        kw["points"], kw["labels"] = [[[w / 2, h / 2]]], [[1]]
        ctx.note("No prompt given, so the object at the center was segmented. Click on the image to choose.")
    r = ctx.predict("sam2", img, **kw)[0]
    if r.masks is None or not len(r.masks):
        raise UserError("SAM didn't return a mask. Try clicking nearer the object's middle.")
    masks = r.masks.data.cpu().numpy() > 0.5
    m = masks.any(0).astype(np.uint8)
    if m.shape != (h, w):
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    out = img.copy()
    out[m > 0] = (out[m > 0] * 0.45 + np.array(AMBER) * 0.55).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, WHITE, 2)
    for x, y in (kw.get("points") or [[]])[0]:
        cv2.circle(out, (int(x), int(y)), 8, GREEN, -1)
    ctx.add_image(out, "Segmented object")
    cut = np.dstack([img, m * 255])
    ctx.add_png(cut, "Cut-out (transparent PNG)")
    ok, mp = cv2.imencode(".png", m * 255)
    ctx.add_file(mp.tobytes(), "mask.png")
    ctx.add_json([c.reshape(-1, 2).tolist() for c in cnts], "polygons.json")
    ctx.stat("Mask area", round(float(m.mean() * 100), 2), unit="% of image")
    ctx.stat("Regions", len(cnts))


# ------------------------------------------------------------------ sign language (hand crops)

@pipeline("sign_language", "Sign language recognition",
          "Locates both hands with YOLO26 pose and classifies each hand crop with your trained sign classifier.",
          MEDIA, [Param("stride", "Video: every Nth frame", "int", 3, 1, 15, advanced=True)],
          models=["yolo26-pose"], custom_task="classify")
def sign_language(ctx):
    from .people import LEL, LWR, REL, RWR, draw_skeleton, largest, pose_predict
    key = ctx.params.get("model")
    has_model = isinstance(key, str) and key.startswith("custom:")

    def fn(img, t, st):
        p = largest(pose_predict(ctx, img, 0.3))
        out = img.copy()
        if p is None:
            return out
        draw_skeleton(out, p)
        for side, (el, wr) in (("left", (LEL, LWR)), ("right", (REL, RWR))):
            if not (p["ok"][el] and p["ok"][wr]):
                continue
            e, wpt = p["kp"][el], p["kp"][wr]
            hand_c = wpt + 0.35 * (wpt - e)
            s = int(max(40, 0.9 * np.linalg.norm(wpt - e)))
            x1, y1 = int(hand_c[0] - s / 2), int(hand_c[1] - s / 2)
            crop = img[max(0, y1):y1 + s, max(0, x1):x1 + s]
            txt = side
            if has_model and crop.size:
                r = ctx.predict(key, crop)[0]
                name, pr = r.names[int(r.probs.top1)], float(r.probs.top1conf)
                txt = f"{name} {pr:.2f}"
                if pr > 0.6 and (not st.get("seq") or st["seq"][-1] != name):
                    st.setdefault("seq", []).append(name)
            box(out, [x1, y1, x1 + s, y1 + s], txt, AMBER)
            if crop.size and len(st.setdefault("crops", [])) < 6 and not st.get("video"):
                st["crops"].append(crop)
        return out

    st = run_media(ctx, fn, caption="Hands")
    for c in st.get("crops", []):
        ctx.add_image(c, "Hand crop")
    if st.get("seq"):
        ctx.text(" ".join(st["seq"]))
        ctx.stat("Signs recognized", len(st["seq"]))
    if not has_model:
        ctx.note("Hands are located, but recognizing signs needs a classifier trained on hand crops (e.g. an ASL or Arabic sign "
                 "alphabet dataset). Train YOLO26-cls on such crops, upload it, and pick it in Model.")
