"""Inspection and measurement: golden template, texture defects, fill level, cracks, particles, cells, dimensions,
thermal hotspots, robot pick points."""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import (AMBER, BLUE, GREEN, IMAGE, MEDIA, RED, STRIDE, WHITE, Param, Slot, UserError, banner, box,
                    boxes_of, classes_param, color_for, fit, label, masks_of, norm_points, pipeline, polygons_param)
from .common import filter_classes, heatmap_overlay, run_media, to_gray


def skeleton(mask: np.ndarray) -> np.ndarray:
    """Morphological skeleton of a binary mask (0/1)."""
    img = (mask > 0).astype(np.uint8) * 255
    skel = np.zeros_like(img)
    el = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(img):
        eroded = cv2.erode(img, el)
        skel |= cv2.subtract(img, cv2.dilate(eroded, el))
        img = eroded
    return (skel > 0).astype(np.uint8)


# ------------------------------------------------------------------ golden template comparison

def align(ref: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, int]:
    orb = cv2.ORB_create(6000)
    k1, d1 = orb.detectAndCompute(to_gray(ref), None)
    k2, d2 = orb.detectAndCompute(to_gray(test), None)
    if d1 is None or d2 is None:
        raise UserError("Not enough detail to align the two images.")
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d2, d1), key=lambda m: m.distance)[:1500]
    if len(matches) < 12:
        raise UserError("The two images don't share enough features to align them. Use the same product and viewpoint.")
    src = np.float32([k2[m.queryIdx].pt for m in matches])
    dst = np.float32([k1[m.trainIdx].pt for m in matches])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        raise UserError("Couldn't align the images.")
    return cv2.warpPerspective(test, H, (ref.shape[1], ref.shape[0]), borderMode=cv2.BORDER_REPLICATE), int(inl.sum())


@pipeline("golden_template", "Golden-template inspection",
          "Aligns a test part to a known-good reference image and highlights everything that differs: missing parts, extra material, damage.",
          [Slot("reference", "Reference (good part)"), Slot("test", "Part to inspect")],
          [Param("threshold", "Difference threshold", "int", 45, 10, 150),
           Param("min_area", "Ignore defects smaller than (px)", "int", 60, 5, 5000)])
def golden_template(ctx):
    ref, test = fit(ctx.image("reference"), 1600), ctx.image("test")
    test = cv2.resize(test, (ref.shape[1], ref.shape[0])) if abs(test.shape[1] / ref.shape[1] - 1) > 0.5 else test
    aligned, inliers = align(ref, test)
    a = cv2.GaussianBlur(cv2.cvtColor(ref, cv2.COLOR_BGR2LAB), (5, 5), 0).astype(np.int16)
    b = cv2.GaussianBlur(cv2.cvtColor(aligned, cv2.COLOR_BGR2LAB), (5, 5), 0).astype(np.int16)
    diff = np.abs(a - b).max(axis=2).astype(np.uint8)
    mask = (diff > int(ctx.p("threshold", 45))).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = aligned.copy()
    rows = []
    edges_r, edges_t = cv2.Canny(to_gray(ref), 60, 160), cv2.Canny(to_gray(aligned), 60, 160)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(c)
        if area < int(ctx.p("min_area", 60)):
            continue
        x, y, w, h = cv2.boundingRect(c)
        er, et = edges_r[y:y + h, x:x + w].mean(), edges_t[y:y + h, x:x + w].mean()
        kind = "missing / removed" if er > et * 1.3 else "extra / added" if et > er * 1.3 else "changed"
        rows.append([len(rows) + 1, kind, int(area), x, y, w, h, int(diff[y:y + h, x:x + w].max())])
        box(out, [x - 4, y - 4, x + w + 4, y + h + 4], f"#{len(rows)} {kind}", RED)
    ctx.add_image(out, "Defects on the aligned part")
    ctx.add_image(heatmap_overlay(aligned, diff.astype(np.float32), 0.6), "Difference heatmap")
    ctx.stat("Result", "PASS" if not rows else "FAIL", "good" if not rows else "bad")
    ctx.stat("Defects", len(rows))
    ctx.stat("Alignment matches", inliers)
    if rows:
        ctx.table("Defects", ["#", "Type", "Area (px)", "x", "y", "w", "h", "Max difference"], rows, "defects.csv")
    ctx.note("Works best with fixed lighting and camera position. Small misalignment shows up as thin outlines; raise the threshold or minimum area to ignore them.")


# ------------------------------------------------------------------ texture defects (fabric)

@pipeline("texture_defect", "Texture defect detection",
          "Finds holes, stains and broken threads in repetitive textures (fabric, mesh, paper) by removing the regular pattern "
          "and flagging what's left.",
          IMAGE, [Param("sensitivity", "Sensitivity (z-score)", "number", 6, 2, 15, 0.5, help="Lower flags more."),
                  Param("min_area", "Ignore defects smaller than (px)", "int", 400, 10, 20000)])
def texture_defect(ctx):
    img = fit(ctx.image(), 1400)
    P = 48
    g = cv2.copyMakeBorder(to_gray(img), P, P, P, P, cv2.BORDER_REFLECT).astype(np.float32)
    # 1) remove the periodic weave in the frequency domain
    F = np.fft.fft2(g - g.mean())
    mag = np.abs(F)
    yy, xx = np.mgrid[0:g.shape[0], 0:g.shape[1]]
    yy = np.minimum(yy, g.shape[0] - yy)
    xx = np.minimum(xx, g.shape[1] - xx)
    low = (yy ** 2 + xx ** 2) < 25
    peaks = (mag > np.percentile(mag[~low], 99.6)) & ~low
    F[cv2.dilate(peaks.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0] = 0
    residual = np.abs(np.fft.ifft2(F))[P:-P, P:-P]
    residual = cv2.GaussianBlur(residual.astype(np.float32), (0, 0), 3)
    # 2) also measure local color deviation (stains with similar texture)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    local = cv2.blur(lab, (31, 31))
    cdev = np.linalg.norm(local - np.median(local.reshape(-1, 3), axis=0), axis=2)

    def z(a):
        med = np.median(a)
        return (a - med) / (np.median(np.abs(a - med)) * 1.4826 + 1e-6)

    score = np.maximum(z(residual), z(cdev))
    m = max(4, int(0.02 * min(score.shape)))
    score[:m], score[-m:], score[:, :m], score[:, -m:] = 0, 0, 0, 0
    sens = float(ctx.p("sensitivity", 6))
    mask = (score > sens).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = img.copy()
    rows = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(c)
        if area < int(ctx.p("min_area", 400)):
            continue
        x, y, w, h = cv2.boundingRect(c)
        if score[y:y + h, x:x + w].max() < 1.5 * sens:
            continue  # weak halo, not a defect
        sb = score[y:y + h, x:x + w]
        core = (sb > 0.6 * sb.max()).astype(np.uint8)
        gray_roi = to_gray(img)[y:y + h, x:x + w]
        roi = gray_roi[core > 0].mean()
        surround = gray_roi[core == 0].mean() if (core == 0).any() else to_gray(img).mean()
        pts = cv2.findNonZero(core)
        (_, _), (cw, ch), _ = cv2.minAreaRect(pts) if pts is not None else ((0, 0), (1, 1), 0)
        elong = max(cw, ch) / max(1, min(cw, ch))
        kind = "line / broken thread" if elong > 4 else "hole / dark spot" if roi < surround - 25 else "stain / discoloration"
        rows.append([len(rows) + 1, kind, int(area), x, y, w, h, round(float(score[y:y + h, x:x + w].max()), 1)])
        box(out, [x - 6, y - 6, x + w + 6, y + h + 6], f"#{len(rows)} {kind}", RED)
    ctx.add_image(out, "Defects")
    ctx.add_image(heatmap_overlay(img, np.clip(score, 0, 12)), "Anomaly map")
    ctx.stat("Result", "PASS" if not rows else "FAIL", "good" if not rows else "bad")
    ctx.stat("Defects", len(rows))
    if rows:
        ctx.table("Defects", ["#", "Type", "Area (px)", "x", "y", "w", "h", "Score"], rows, "fabric_defects.csv")
    ctx.note("For irregular textures or subtle defects, train an anomaly model (e.g. PatchCore via anomalib) on images of good material only.")


# ------------------------------------------------------------------ fill level

def silhouettes(img) -> list[dict]:
    """Tall objects standing out from a plain background (classical backlit inspection)."""
    g = to_gray(img)
    bg = np.median(g[: max(5, img.shape[0] // 20)].astype(np.int16), axis=0)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    fg = ((np.abs(g.astype(np.int16) - bg[None, :]) > 12) | (hsv[..., 1] > 70)).astype(np.uint8)
    fg |= cv2.dilate(cv2.Canny(g, 30, 90), np.ones((3, 3), np.uint8)) // 255
    band = cv2.morphologyEx(fg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (img.shape[1] // 2, 1)))
    fg = fg & (1 - band)   # drop conveyor belts and other full-width bands
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    filled = np.zeros_like(fg)
    cv2.drawContours(filled, cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, 1, -1)
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    out = []
    for c in cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if h > 1.6 * w and h > 0.2 * img.shape[0] and w > 0.02 * img.shape[1]:
            out.append({"box": [x, y, x + w, y + h], "conf": 0.5, "cls": "bottle"})
    return out


def liquid_level(img, b) -> int | None:
    """Row of the liquid surface inside a bottle box, or None."""
    g = to_gray(img).astype(np.float32)
    x1, y1, x2, y2 = map(int, b)
    w = x2 - x1
    cx1, cx2 = x1 + int(0.42 * w), x2 - int(0.42 * w)
    if cx2 <= cx1 or y2 - y1 < 20:
        return None
    prof = cv2.GaussianBlur(g[y1:y2, cx1:cx2].mean(axis=1).reshape(-1, 1), (1, 5), 0).ravel()
    n = len(prof)
    liquid = float(np.median(prof[-max(3, n // 5):]))
    side = g[y1:y2, max(0, x1 - 15):max(1, x1 - 3)]
    bgv = float(np.median(side)) if side.size else float(np.median(g[:10]))
    if abs(bgv - liquid) > 25:
        thr = (bgv + liquid) / 2
        inside = (prof < thr) if liquid < bgv else (prof > thr)
        start = next((i for i in range(int(0.02 * n), n) if not inside[i]), None)   # first empty-glass row below the cap
        if start is None:
            return y1   # liquid all the way up
        k = next((i for i in range(start, n - 5) if inside[i:i + 5].all()), None)
        return None if k is None else y1 + k
    grad = np.abs(np.diff(prof[int(0.15 * n):]))
    k = int(np.argmax(grad)) if len(grad) else 0
    return y1 + int(0.15 * n) + k if len(grad) and grad[k] > 4 else None


@pipeline("fill_level", "Bottle fill-level inspection",
          "Finds bottles, measures the liquid level in each, and checks the cap.",
          MEDIA, [Param("min_fill", "Minimum fill (%)", "int", 70, 10, 100), Param("max_fill", "Maximum fill (%)", "int", 92, 10, 100),
                  Param("check_caps", "Check caps (YOLOE-26)", "bool", True),
                  Param("conf", "Bottle confidence", "number", 0.25, 0.05, 0.9, 0.05), STRIDE],
          models=["yolo26-detect", "yoloe26"], custom_task="detect")
def fill_level(ctx):
    lo, hi = int(ctx.p("min_fill", 70)), int(ctx.p("max_fill", 92))

    def fn(img, t, st):
        conf = float(ctx.p("conf", 0.25))
        bottles = [d for d in boxes_of(ctx.predict(ctx.model_key("yolo26-detect"), img, conf=conf)[0]) if d["cls"] in ("bottle", "wine glass", "cup")]
        classical = False
        if not bottles:
            bottles = boxes_of(ctx.yoloe(["bottle"], img, conf=max(0.1, conf - 0.1))[0])
        if not bottles:
            bottles, classical = silhouettes(img), True
            if bottles:
                st["classical"] = True
        caps = boxes_of(ctx.yoloe(["bottle cap"], img, conf=0.15)[0]) if ctx.p("check_caps", True) and not classical else []
        out = img.copy()
        rows = []
        g = to_gray(img).astype(np.float32)
        for i, b in enumerate(sorted(bottles, key=lambda d: d["box"][0])):
            x1, y1, x2, y2 = map(int, b["box"])
            level = liquid_level(img, b["box"])
            fill = round((y2 - level) / (y2 - y1) * 100) if level is not None else None
            if not ctx.p("check_caps", True):
                has_cap = None
            elif classical:
                strip = cv2.cvtColor(img[y1:y1 + max(3, int(0.08 * (y2 - y1))), x1 + int(0.3 * (x2 - x1)):x2 - int(0.3 * (x2 - x1))], cv2.COLOR_BGR2HSV)
                has_cap = bool(strip.size and (strip[..., 1] > 80).mean() > 0.4)
            else:
                has_cap = any(c["box"][1] < y1 + 0.25 * (y2 - y1) and x1 - 10 < (c["box"][0] + c["box"][2]) / 2 < x2 + 10 for c in caps)
            status = "no level" if fill is None else "underfilled" if fill < lo else "overfilled" if fill > hi else "ok"
            if has_cap is False:
                status = (status + ", no cap") if status != "ok" else "no cap"
            col = GREEN if status == "ok" else RED
            box(out, b["box"], f"#{i + 1} {fill}% {status}" if fill is not None else f"#{i + 1} {status}", col)
            if level is not None:
                cv2.line(out, (x1, level), (x2, level), BLUE, 3)
            rows.append([i + 1, fill, status, "yes" if has_cap else "no" if has_cap is False else "n/a"])
        st["rows"] = rows
        return out

    st = run_media(ctx, fn, caption="Fill levels")
    rows = st.get("rows", [])
    if st.get("classical"):
        ctx.note("The models didn't recognize these bottles, so they were found as silhouettes against the plain background.")
    ctx.stat("Bottles", len(rows))
    ctx.stat("Passed", sum(r[2] == "ok" for r in rows), "good")
    ctx.stat("Rejected", sum(r[2] != "ok" for r in rows), "bad" if any(r[2] != "ok" for r in rows) else "good")
    if rows:
        ctx.table("Bottles", ["#", "Fill %", "Status", "Cap"], rows, "fill_levels.csv")
    ctx.note("Use a plain backlit background for best results. Fill % is measured from the bottom of the bottle's box.")


# ------------------------------------------------------------------ cracks

@pipeline("crack_analysis", "Crack detection and measurement",
          "Segments cracks in concrete or asphalt and measures their length and width.",
          IMAGE, [Param("mm_per_px", "Scale (mm per pixel)", "number", 0.5, 0.01, 50, 0.01, help="Measure a known object in the photo to set this."),
                  Param("sensitivity", "Sensitivity", "int", 18, 5, 80, help="Lower finds fainter cracks."),
                  Param("min_length", "Ignore cracks shorter than (px)", "int", 60, 5, 2000)])
def crack_analysis(ctx):
    img = fit(ctx.image(), 1600)
    g = cv2.createCLAHE(2.0, (8, 8)).apply(to_gray(img))
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    bhs = cv2.GaussianBlur(bh, (3, 3), 0)
    thr = max(int(ctx.p("sensitivity", 18)), float(np.percentile(bhs, 98)))   # adapt to surface texture
    mask = (bhs > thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    mmpp = float(ctx.p("mm_per_px", 0.5))
    rows = []
    skel_all = np.zeros_like(mask)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if max(w, h) < int(ctx.p("min_length", 60)) or a > 0.3 * mask.size:
            continue
        comp = (lab == i).astype(np.uint8)
        sk = skeleton(comp)
        length_px = int(sk.sum())
        if length_px < int(ctx.p("min_length", 60)) or a / max(length_px, 1) > 25:
            continue  # too short, or too thick to be a crack
        widths = dist[sk > 0] * 2
        keep |= comp
        skel_all |= sk
        wmax, wmean = float(widths.max()) * mmpp, float(widths.mean()) * mmpp
        sev = "hairline" if wmax < 0.3 else "fine" if wmax < 1 else "medium" if wmax < 3 else "wide"
        rows.append([len(rows) + 1, round(length_px * mmpp), round(wmean, 2), round(wmax, 2), sev, x, y, w, h])
    out = img.copy()
    out[keep > 0] = (out[keep > 0] * 0.3 + np.array(RED) * 0.7).astype(np.uint8)
    out[cv2.dilate(skel_all, np.ones((2, 2), np.uint8)) > 0] = (60, 230, 255)
    for r in rows:
        label(out, f"#{r[0]} {r[1]} mm", r[5], r[6], AMBER)
    ctx.add_image(out, "Cracks (yellow = centerline)")
    ctx.stat("Cracks", len(rows), "bad" if rows else "good")
    if rows:
        ctx.stat("Total length", sum(r[1] for r in rows), unit="mm")
        ctx.stat("Widest", max(r[3] for r in rows), unit="mm")
        ctx.table("Cracks", ["#", "Length (mm)", "Mean width (mm)", "Max width (mm)", "Severity", "x", "y", "w", "h"], rows, "cracks.csv")
    ctx.note("Classical segmentation. Shadows and joints can look like cracks; a U-Net trained on crack datasets (e.g. CRACK500) is more robust.")


# ------------------------------------------------------------------ particles

def segment_blobs(img, invert: str = "auto", split: bool = True):
    g = cv2.GaussianBlur(to_gray(img), (5, 5), 0)
    dark_on_light = g.mean() > 127 if invert == "auto" else invert == "dark"
    th = cv2.threshold(g, 0, 255, (cv2.THRESH_BINARY_INV if dark_on_light else cv2.THRESH_BINARY) + cv2.THRESH_OTSU)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=2)
    if not split:
        return cv2.connectedComponentsWithStats((th > 0).astype(np.uint8), 8)[1], th
    dist = cv2.distanceTransform(th, cv2.DIST_L2, 5)
    _, fg = cv2.threshold(dist, 0.45 * dist.max(), 255, 0)
    fg = fg.astype(np.uint8)
    n, markers = cv2.connectedComponents(fg)
    markers = markers + 1
    unknown = cv2.subtract(cv2.dilate(th, np.ones((3, 3), np.uint8), iterations=3), fg)
    markers[unknown == 255] = 0
    markers = cv2.watershed(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), markers)
    markers[markers <= 1] = 0
    return markers, th


@pipeline("particle_analysis", "Particle detection and size measurement",
          "Separates touching particles and measures size, shape and the size distribution (D10/D50/D90).",
          IMAGE, [Param("um_per_px", "Scale (µm per pixel)", "number", 1.0, 0.001, 1000, 0.001),
                  Param("polarity", "Particles are", "select", "auto", options=["auto", "dark", "light"]),
                  Param("min_area", "Ignore particles smaller than (px)", "int", 25, 1, 5000)])
def particle_analysis(ctx):
    img = fit(ctx.image(), 1600)
    markers, _ = segment_blobs(img, ctx.p("polarity", "auto"))
    s = float(ctx.p("um_per_px", 1.0))
    out = img.copy()
    rows = []
    for lbl in np.unique(markers):
        if lbl == 0:
            continue
        m = (markers == lbl).astype(np.uint8)
        a = int(m.sum())
        if a < int(ctx.p("min_area", 25)):
            continue
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        per = cv2.arcLength(c, True)
        (cx, cy), (w, h), ang = cv2.minAreaRect(c)
        d_eq = math.sqrt(4 * a / math.pi)
        circ = 4 * math.pi * a / max(per ** 2, 1)
        rows.append([len(rows) + 1, round(a * s * s, 1), round(d_eq * s, 2), round(circ, 2), round(max(w, h) / max(1, min(w, h)), 2),
                     round(cx), round(cy)])
        cv2.drawContours(out, [c], -1, color_for(str(len(rows))), 2)
    if not rows:
        raise UserError("No particles found. Try the other polarity or a higher-contrast image.")
    d = np.array([r[2] for r in rows])
    ctx.add_image(out, "Particles")
    ctx.stat("Particles", len(rows))
    ctx.stat("D10", round(float(np.percentile(d, 10)), 2), unit="µm")
    ctx.stat("D50 (median)", round(float(np.percentile(d, 50)), 2), unit="µm")
    ctx.stat("D90", round(float(np.percentile(d, 90)), 2), unit="µm")
    ctx.stat("Mean circularity", round(float(np.mean([r[3] for r in rows])), 2))
    hist, edges = np.histogram(d, bins=min(15, max(5, len(d) // 5)))
    ctx.chart("bar", "Size distribution", [f"{edges[i]:.1f}–{edges[i + 1]:.1f}" for i in range(len(hist))],
              [{"name": "Particles", "values": hist.tolist()}], "Equivalent diameter (µm)", "Count")
    ctx.table("Particles", ["#", "Area (µm²)", "Eq. diameter (µm)", "Circularity", "Aspect ratio", "x", "y"], rows, "particles.csv")


# ------------------------------------------------------------------ blood cells

@pipeline("cell_counting", "Blood cell detection and counting",
          "Counts red blood cells and stained white blood cells in a smear image.",
          IMAGE, [Param("rbc_radius", "Typical red cell radius (px)", "int", 27, 4, 120),
                  Param("wbc_threshold", "White-cell stain darkness", "int", 110, 30, 220, help="Lower = only the darkest purple nuclei.")])
def cell_counting(ctx):
    img = fit(ctx.image(), 1600)
    r = int(ctx.p("rbc_radius", 27))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    # WBC nuclei: dark and bluish-purple (high b-channel deficit, low lightness)
    nuc = ((lab[..., 0] < int(ctx.p("wbc_threshold", 110))) & (hsv[..., 1] > 60)).astype(np.uint8)
    nuc = cv2.morphologyEx(nuc, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    nuc = cv2.morphologyEx(nuc, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab_n, stats, cents = cv2.connectedComponentsWithStats(nuc, 8)
    wbcs = [(int(cents[i][0]), int(cents[i][1]), stats[i]) for i in range(1, n) if stats[i][4] > math.pi * (r * 0.5) ** 2]
    g = cv2.medianBlur(to_gray(img), 5)
    circles = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, 1.2, int(r * 1.4), param1=60, param2=22,
                               minRadius=int(r * 0.7), maxRadius=int(r * 1.3))
    rbcs = []
    for x, y, rr in (circles[0] if circles is not None else []):
        if all(math.hypot(x - wx, y - wy) > r * 1.6 for wx, wy, _ in wbcs):
            rbcs.append((int(x), int(y), int(rr)))
    out = img.copy()
    for x, y, rr in rbcs:
        cv2.circle(out, (x, y), rr, RED, 2, cv2.LINE_AA)
    for x, y, s_ in wbcs:
        cv2.rectangle(out, (s_[0] - 8, s_[1] - 8), (s_[0] + s_[2] + 8, s_[1] + s_[3] + 8), BLUE, 3)
        label(out, "WBC", s_[0] - 8, s_[1] - 8, BLUE, WHITE)
    banner(out, [f"RBC: {len(rbcs)}", f"WBC: {len(wbcs)}"])
    ctx.add_image(out, "Cells")
    ctx.stat("Red blood cells", len(rbcs))
    ctx.stat("White blood cells", len(wbcs))
    if wbcs:
        ctx.stat("RBC : WBC", f"{round(len(rbcs) / len(wbcs))} : 1")
    ctx.note("Classical counting for education and research. Clinical counts need a validated system; a YOLO26 model trained on BCCD-style data separates cell types more reliably.")


# ------------------------------------------------------------------ object dimensions (reference object)

@pipeline("object_measurement", "Object and package dimensions",
          "Measures objects on a plain background using a reference object of known width (the left-most object).",
          IMAGE, [Param("ref_width", "Reference object width (mm)", "number", 25, 1, 5000, 0.5,
                        help="e.g. 25 mm coin, 85.6 mm bank card, 210 mm A4 sheet. Put it left of the other objects."),
                  Param("min_area", "Ignore objects smaller than (% of image)", "number", 0.3, 0.01, 20, 0.05)])
def object_measurement(ctx):
    img = fit(ctx.image(), 1600)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    g = to_gray(img)
    bg_g = np.median(np.r_[g[0], g[-1], g[:, 0], g[:, -1]])
    fg = ((np.abs(g.astype(int) - bg_g) > 30) | (hsv[..., 1] > 60)).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) > float(ctx.p("min_area", 0.3)) / 100 * fg.size]
    if len(cnts) < 2:
        raise UserError("Need a reference object plus at least one object to measure, on a plain contrasting background.")
    cnts.sort(key=lambda c: cv2.boundingRect(c)[0])
    ref = cnts[0]
    (_, _), (rw, rh), _ = cv2.minAreaRect(ref)
    px_per_mm = max(rw, rh) / float(ctx.p("ref_width", 25))
    out = img.copy()
    rows = []
    for i, c in enumerate(cnts):
        rect = cv2.minAreaRect(c)
        (cx, cy), (w, h), ang = rect
        pts = cv2.boxPoints(rect).astype(np.int32)
        L, W = max(w, h) / px_per_mm, min(w, h) / px_per_mm
        circ = 4 * math.pi * cv2.contourArea(c) / max(cv2.arcLength(c, True) ** 2, 1)
        shape = "round" if circ > 0.85 else "rectangular" if cv2.contourArea(c) / max(w * h, 1) > 0.9 else "irregular"
        cv2.polylines(out, [pts], True, BLUE if i == 0 else GREEN, 3, cv2.LINE_AA)
        txt = "reference" if i == 0 else (f"Ø {L:.0f} mm" if shape == "round" else f"{L:.0f} × {W:.0f} mm")
        label(out, txt, int(pts[:, 0].min()), int(pts[:, 1].min()), BLUE if i == 0 else GREEN, WHITE)
        if i:
            rows.append([i, shape, round(L, 1), round(W, 1), round(cv2.contourArea(c) / px_per_mm ** 2 / 100, 1), round(ang, 1)])
    ctx.add_image(out, "Measurements")
    ctx.stat("Objects measured", len(rows))
    ctx.stat("Scale", round(1 / px_per_mm, 3), unit="mm/px")
    ctx.table("Dimensions", ["#", "Shape", "Length (mm)", "Width (mm)", "Area (cm²)", "Angle (°)"], rows, "dimensions.csv")
    ctx.note("Measures the top-down outline. For box height, take a second photo from the side or use a depth camera.")


# ------------------------------------------------------------------ thermal hotspots

@pipeline("thermal_hotspots", "Thermal hotspot detection",
          "Finds abnormally hot regions in a thermal image (e.g. a failing solar cell) and estimates their temperature rise.",
          IMAGE, [Param("t_min", "Palette minimum (°C)", "number", 20, -50, 500, 1),
                  Param("t_max", "Palette maximum (°C)", "number", 80, -50, 1000, 1),
                  Param("delta", "Hotspot if hotter than median by (°C)", "number", 10, 1, 200, 1),
                  Param("min_area", "Ignore spots smaller than (px)", "int", 40, 1, 10000)])
def thermal_hotspots(ctx):
    img = fit(ctx.image(), 1600)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # iron/inferno-style palettes run dark → purple → orange → yellow/white: brightness tracks temperature
    v = (0.6 * hsv[..., 2] + 0.4 * to_gray(img)).astype(np.float32) / 255
    t0, t1 = float(ctx.p("t_min", 20)), float(ctx.p("t_max", 80))
    temp = t0 + v * (t1 - t0)
    med = float(np.median(temp))
    mask = (temp > med + float(ctx.p("delta", 10))).astype(np.uint8)
    # ignore the cold background: only spots surrounded by warm surface
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = img.copy()
    rows = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < int(ctx.p("min_area", 40)):
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w * h > 0.25 * temp.size:
            continue
        peak = float(temp[y:y + h, x:x + w].max())
        rows.append([len(rows) + 1, round(peak, 1), round(peak - med, 1), x, y, w, h])
        box(out, [x - 6, y - 6, x + w + 6, y + h + 6], f"#{len(rows)} +{peak - med:.0f}°C", (255, 255, 255))
    ctx.add_image(out, "Hotspots")
    ctx.stat("Hotspots", len(rows), "bad" if rows else "good")
    ctx.stat("Median surface", round(med, 1), unit="°C")
    if rows:
        ctx.stat("Hottest", rows[0][1], unit="°C")
        ctx.table("Hotspots", ["#", "Peak (°C)", "Above median (°C)", "x", "y", "w", "h"], rows, "hotspots.csv")
    ctx.note("Temperatures are estimated from the color palette. Use the camera's radiometric export (raw temperatures) for exact values.")


# ------------------------------------------------------------------ robot picking

@pipeline("robot_picking", "Vision-guided pick points",
          "Segments objects with YOLO26, computes a grasp point, orientation and gripper width for each, and converts them to "
          "robot coordinates if you calibrate four points.",
          IMAGE, [classes_param([], "Objects to pick"),
                  Param("calib", "Calibration points (image)", "polygon", [], help="Click 4 points whose real positions you know."),
                  Param("world", "Their real positions (mm)", "text", "0,0; 400,0; 400,300; 0,300", help="Same order as the clicks: x,y; x,y; …"),
                  Param("conf", "Confidence threshold", "number", 0.3, 0.05, 0.95, 0.05)],
          models=["yolo26-segment"], custom_task="segment")
def robot_picking(ctx):
    img = ctx.image()
    h, w = img.shape[:2]
    r = ctx.predict(ctx.model_key("yolo26-segment"), img, conf=float(ctx.p("conf", 0.3)))[0]
    dets = filter_classes(boxes_of(r), ctx.p("classes", []))
    masks = masks_of(r, img.shape)
    Hm = None
    calib = norm_points(ctx.p("calib"), w, h)
    if len(calib) >= 4:
        try:
            world = np.float32([[float(v) for v in p.split(",")] for p in str(ctx.p("world", "")).split(";") if p.strip()])
            if len(world) >= 4:
                Hm = cv2.getPerspectiveTransform(calib[:4].astype(np.float32), world[:4])
        except ValueError:
            raise UserError("Real positions must look like '0,0; 400,0; 400,300; 0,300'.")
    out = img.copy()
    rows = []
    for d in sorted(dets, key=lambda d: -d["conf"]):
        m = masks[d["i"]] if d["i"] < len(masks) else None
        if m is None or not m.any():
            continue
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        M = cv2.moments(c)
        cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
        (_, _), (rw, rh), ang = cv2.minAreaRect(c)
        grasp_ang = ang if rw < rh else ang + 90   # close the gripper across the narrow side
        width_px = min(rw, rh)
        wx = wy = None
        if Hm is not None:
            p = cv2.perspectiveTransform(np.float32([[[cx, cy]]]), Hm)[0, 0]
            wx, wy = round(float(p[0]), 1), round(float(p[1]), 1)
        rows.append([len(rows) + 1, d["cls"], round(cx), round(cy), wx, wy, round(grasp_ang % 180, 1), round(width_px), round(d["conf"], 2)])
        a = math.radians(grasp_ang)
        dx, dy = math.cos(a) * width_px * 0.7, math.sin(a) * width_px * 0.7
        cv2.drawContours(out, [c], -1, color_for(d["cls"]), 2)
        cv2.line(out, (int(cx - dx), int(cy - dy)), (int(cx + dx), int(cy + dy)), GREEN, 4, cv2.LINE_AA)
        cv2.circle(out, (int(cx), int(cy)), 8, RED, -1, cv2.LINE_AA)
        label(out, f"{len(rows)}. {d['cls']}", int(cx) + 10, int(cy) - 10, AMBER)
    if len(calib):
        for p in calib[:4]:
            cv2.drawMarker(out, tuple(map(int, p)), BLUE, cv2.MARKER_CROSS, 30, 3)
    ctx.add_image(out, "Pick points (green = gripper closing direction)")
    ctx.stat("Objects", len(rows))
    ctx.stat("Calibrated", "yes" if Hm is not None else "no", "good" if Hm is not None else "warn")
    ctx.table("Pick list", ["Order", "Object", "x (px)", "y (px)", "x (mm)", "y (mm)", "Angle (°)", "Gripper width (px)", "Conf"], rows, "picks.csv")
    if Hm is None:
        ctx.note("Click 4 reference points on the image and enter their real positions to get robot coordinates in mm.")
