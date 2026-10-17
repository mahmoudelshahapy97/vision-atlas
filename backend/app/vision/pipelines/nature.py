"""Agriculture, environment, science and geospatial: leaf health, ripeness, coral, galaxies, land cover,
field boundaries, building footprints, floor plans."""
from __future__ import annotations

import json
import math

import cv2
import numpy as np

from ..core import (AMBER, BLUE, GREEN, IMAGE, RED, WHITE, Param, UserError, banner, box, boxes_of, color_for, fit,
                    label, masks_of, pipeline)
from .common import mask_area_pct, prompts_list, to_gray


def _geojson(polys: list[tuple[np.ndarray, dict]], scale: float | None) -> dict:
    feats = []
    for poly, props in polys:
        coords = (poly.reshape(-1, 2) * (scale or 1)).round(2).tolist()
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        feats.append({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [coords]}})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"units": "meters from image top-left" if scale else "pixels from image top-left"}}


# ------------------------------------------------------------------ leaf health

@pipeline("leaf_health", "Plant disease severity",
          "Segments the leaf, then measures the share of yellowing (chlorosis) and brown lesions (necrosis) and counts spots.",
          IMAGE, [Param("min_spot", "Ignore spots smaller than (px)", "int", 30, 1, 5000)])
def leaf_health(ctx):
    img = fit(ctx.image(), 1600)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    leaf = ((s > 45) & (v > 30)).astype(np.uint8)
    leaf = cv2.morphologyEx(leaf, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(leaf, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise UserError("Couldn't separate the leaf from the background. Use a plain, light background.")
    leaf = np.zeros_like(leaf)
    cv2.drawContours(leaf, [max(cnts, key=cv2.contourArea)], -1, 1, -1)
    green = leaf & ((h >= 33) & (h <= 90)).astype(np.uint8)
    yellow = leaf & ((h >= 18) & (h < 33) & (v > 90)).astype(np.uint8)
    brown = leaf & (1 - green) & (1 - yellow)
    la = max(1, int(leaf.sum()))
    pct = lambda m: float(m.sum()) / la * 100
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(brown, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), 8)
    spots = [i for i in range(1, n) if stats[i][4] >= int(ctx.p("min_spot", 30))]
    sev_pct = pct(brown) + 0.5 * pct(yellow)
    grade = 0 if sev_pct < 1 else 1 if sev_pct < 5 else 2 if sev_pct < 15 else 3 if sev_pct < 30 else 4
    out = img.copy()
    out[yellow > 0] = (out[yellow > 0] * 0.4 + np.array((0, 220, 255)) * 0.6).astype(np.uint8)
    out[brown > 0] = (out[brown > 0] * 0.3 + np.array((30, 30, 200)) * 0.7).astype(np.uint8)
    cv2.drawContours(out, cv2.findContours(leaf, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, GREEN, 3)
    banner(out, [f"Severity grade {grade}/4", f"Lesions {pct(brown):.1f}%  ·  Yellowing {pct(yellow):.1f}%"])
    ctx.add_image(out, "Lesions (red) and yellowing (yellow)")
    ctx.stat("Severity grade", f"{grade} / 4", "good" if grade <= 1 else "bad")
    ctx.stat("Healthy tissue", round(pct(green), 1), unit="%")
    ctx.stat("Lesions", round(pct(brown), 1), unit="%")
    ctx.stat("Yellowing", round(pct(yellow), 1), unit="%")
    ctx.stat("Spots", len(spots))
    ctx.chart("bar", "Leaf area", ["Healthy", "Yellowing", "Lesions"], [{"name": "% of leaf", "values": [round(pct(green), 1), round(pct(yellow), 1), round(pct(brown), 1)]}])
    ctx.note("This measures visible damage, not which disease it is. To name the disease, train a YOLO26 classifier on PlantVillage-style images and upload it to the Classification lab.")


# ------------------------------------------------------------------ fruit ripeness

RIPE_HUES = {"banana": [(18, 32)], "apple": [(0, 10), (165, 180)], "orange": [(8, 22)], "tomato": [(0, 10), (165, 180)],
             "strawberry": [(0, 10), (165, 180)], "mango": [(10, 28)], "lemon": [(22, 34)]}


@pipeline("fruit_ripeness", "Fruit detection and ripeness",
          "Detects and counts fruit, then grades each one unripe, ripe or overripe from its color.",
          IMAGE, [Param("fruits", "Fruits", "text", "apple, orange, banana, tomato, strawberry, mango"),
                  Param("conf", "Confidence threshold", "number", 0.2, 0.05, 0.9, 0.05)],
          models=["yoloe26"])
def fruit_ripeness(ctx):
    img = ctx.image()
    names = prompts_list(ctx.p("fruits"))
    r = ctx.yoloe(names, img, conf=float(ctx.p("conf", 0.2)))[0]
    dets = boxes_of(r)
    masks = masks_of(r, img.shape)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = img.copy()
    rows = []
    for d in dets:
        m = masks[d["i"]].astype(bool) if d["i"] < len(masks) else None
        if m is None or m.sum() < 30:
            continue
        hh, ss, vv = hsv[..., 0][m].astype(int), hsv[..., 1][m].astype(int), hsv[..., 2][m].astype(int)
        fruit = d["cls"].lower()
        ripe_ranges = RIPE_HUES.get(fruit, [(0, 30), (165, 180)])
        ripe = np.zeros_like(hh, bool)
        for a, b in ripe_ranges:
            ripe |= (hh >= a) & (hh <= b) & (ss > 60)
        greenish = (hh > 33) & (hh < 90) & (ss > 50)
        dark = (vv < 70) | ((hh < 20) & (ss < 120) & (vv < 120))
        rp, gp, dp = ripe.mean(), greenish.mean(), dark.mean()
        stage = "overripe" if dp > 0.25 else "ripe" if rp > gp and rp > 0.3 else "unripe" if gp > 0.3 else "turning"
        col = {"ripe": GREEN, "unripe": (60, 200, 60), "turning": AMBER, "overripe": RED}[stage]
        box(out, d["box"], f"{d['cls']} {stage}", col)
        rows.append([len(rows) + 1, d["cls"], stage, round(rp * 100), round(gp * 100), round(dp * 100), round(d["conf"], 2)])
    ctx.add_image(out, "Fruit and ripeness")
    ctx.stat("Fruit", len(rows))
    for stg in ("unripe", "turning", "ripe", "overripe"):
        n = sum(r_[2] == stg for r_ in rows)
        if n:
            ctx.stat(stg.capitalize(), n)
    if rows:
        ctx.table("Fruit", ["#", "Fruit", "Stage", "Ripe color %", "Green %", "Dark/brown %", "Conf"], rows, "fruit.csv")
    else:
        ctx.note("No fruit found. Try listing the fruit you expect in 'Fruits', or lower the confidence.")
    ctx.note("Color-based grading. Calibrate the stages per variety, or train a YOLO26 model with one class per stage.")


# ------------------------------------------------------------------ coral health

@pipeline("coral_health", "Coral reef bleaching index",
          "Separates coral from water and measures the share that looks bleached (white, low color).",
          IMAGE, [Param("white", "Bleached if brightness above", "int", 185, 120, 250),
                  Param("color", "…and color saturation below", "int", 45, 10, 120)])
def coral_health(ctx):
    img = fit(ctx.image(), 1600)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    water = ((h >= 85) & (h <= 130) & (s > 60)).astype(np.uint8)
    bleached = ((v > int(ctx.p("white", 185))) & (s < int(ctx.p("color", 45)))).astype(np.uint8)
    coral = ((1 - water) | bleached).astype(np.uint8)
    coral = cv2.morphologyEx(coral, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    bleached &= coral
    ca = max(1, int(coral.sum()))
    idx = bleached.sum() / ca * 100
    out = img.copy()
    out[bleached > 0] = (out[bleached > 0] * 0.3 + np.array(RED) * 0.7).astype(np.uint8)
    cv2.drawContours(out, cv2.findContours(coral, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], -1, GREEN, 2)
    banner(out, [f"Bleaching index {idx:.1f}%", f"Coral cover {coral.mean() * 100:.1f}%"])
    ctx.add_image(out, "Coral (green outline) and bleached areas (red)")
    ctx.stat("Bleaching index", round(idx, 1), "bad" if idx > 20 else "warn" if idx > 5 else "good", "%")
    ctx.stat("Coral cover", round(float(coral.mean() * 100), 1), unit="%")
    ctx.stat("Water", round(float(water.mean() * 100), 1), unit="%")
    ctx.note("Compare images of the same site over time with the same camera settings. White sand and lighting can look like bleaching.")


# ------------------------------------------------------------------ galaxy morphology (CAS)

@pipeline("galaxy_morphology", "Galaxy morphology (CAS)",
          "Measures concentration, asymmetry and clumpiness (the CAS system used in astronomy) and suggests a Hubble type.",
          IMAGE, [Param("sigma", "Detection threshold (σ above sky)", "number", 2.0, 0.5, 10, 0.5)])
def galaxy_morphology(ctx):
    img = fit(ctx.image(), 1200)
    g = to_gray(img).astype(np.float32)
    sky = np.median(g)
    noise = np.median(np.abs(g - sky)) * 1.4826 + 1e-3
    I = np.clip(g - sky, 0, None)
    seg = (I > float(ctx.p("sigma", 2.0)) * noise).astype(np.uint8)
    seg = cv2.morphologyEx(seg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, cents = cv2.connectedComponentsWithStats(seg, 8)
    if n < 2:
        raise UserError("No galaxy found above the sky background.")
    k = 1 + int(np.argmax(stats[1:, 4]))
    gm = (lab == k).astype(np.float32)
    Ig = I * gm
    tot = Ig.sum()
    yy, xx = np.indices(I.shape)
    cx, cy = (Ig * xx).sum() / tot, (Ig * yy).sum() / tot
    r = np.hypot(xx - cx, yy - cy)
    order = np.argsort(r[gm > 0])
    rr, flux = r[gm > 0][order], np.cumsum(Ig[gm > 0][order]) / tot
    r20, r50, r80 = (float(rr[np.searchsorted(flux, q)]) for q in (0.2, 0.5, 0.8))
    C = 5 * math.log10(max(r80, 1) / max(r20, 1))
    M = cv2.getRotationMatrix2D((cx, cy), 180, 1.0)
    rot = cv2.warpAffine(Ig, M, (I.shape[1], I.shape[0]))
    A = float(np.abs(Ig - rot).sum() / (2 * tot))
    sm = cv2.GaussianBlur(Ig, (0, 0), max(1.0, 0.25 * r50))
    S = float(np.clip(Ig - sm, 0, None).sum() / tot)
    mu20, mu02, mu11 = (Ig * (xx - cx) ** 2).sum() / tot, (Ig * (yy - cy) ** 2).sum() / tot, (Ig * (xx - cx) * (yy - cy)).sum() / tot
    lam = np.linalg.eigvalsh(np.array([[mu20, mu11], [mu11, mu02]]))
    ell = 1 - math.sqrt(max(lam[0], 1e-6) / max(lam[1], 1e-6))
    if A > 0.35:
        t = "Irregular / merger"
    elif ell > 0.65:
        t = "Edge-on disk"
    elif C > 3.8 and A < 0.12 and S < 0.12:
        t = "Elliptical (E)"
    elif C > 3.3 and S < 0.15:
        t = "Lenticular / early spiral (S0–Sa)"
    else:
        t = "Spiral (Sb–Sd)"
    out = img.copy()
    for rad, col in ((r20, BLUE), (r50, GREEN), (r80, AMBER)):
        cv2.circle(out, (int(cx), int(cy)), int(rad), col, 2, cv2.LINE_AA)
    banner(out, [t, f"C={C:.2f}  A={A:.2f}  S={S:.2f}"])
    ctx.add_image(out, "r20 (blue), r50 (green), r80 (amber)")
    ctx.stat("Suggested type", t)
    ctx.stat("Concentration C", round(C, 2))
    ctx.stat("Asymmetry A", round(A, 3))
    ctx.stat("Clumpiness S", round(S, 3))
    ctx.stat("Ellipticity", round(ell, 2))
    radii = np.linspace(1, r80 * 1.5, 30)
    prof = [float(I[(r >= a) & (r < a + radii[1] - radii[0])].mean()) if ((r >= a) & (r < a + radii[1] - radii[0])).any() else 0 for a in radii]
    ctx.chart("line", "Radial brightness profile", [round(x, 1) for x in radii], [{"name": "Mean brightness", "values": [round(p, 2) for p in prof]}], "Radius (px)")
    ctx.note("CAS thresholds follow Conselice (2003) and are indicative. A CNN trained on Galaxy Zoo labels gives finer classes.")


# ------------------------------------------------------------------ land cover

LC = {"vegetation": (60, 160, 70), "water": (190, 110, 30), "built / road": (150, 150, 150), "bare soil": (70, 140, 200), "other": (60, 60, 60)}


@pipeline("land_cover", "Satellite land-cover mapping",
          "Classifies every pixel of an aerial or satellite image as vegetation, water, built-up or bare soil, "
          "and optionally finds objects with YOLO26-OBB.",
          IMAGE, [Param("gsd", "Ground resolution (m per pixel)", "number", 0, 0, 100, 0.1, help="0 = unknown (areas in %)."),
                  Param("objects", "Also detect objects (YOLO26-OBB)", "bool", False)],
          models=["yolo26-obb"])
def land_cover(ctx):
    img = fit(ctx.image(), 2000)
    f = img.astype(np.float32) / 255
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    exg = 2 * g - r - b
    lab = np.full(img.shape[:2], 4, np.uint8)
    lab[(s < 40) & (v > 110)] = 2
    lab[(h >= 5) & (h <= 25) & (s >= 40) & (exg < 0.05)] = 3
    lab[exg > 0.06] = 0
    lab[(b > g) & (b > r) & (h >= 90) & (h <= 130) & (s > 50)] = 1
    lab = cv2.medianBlur(lab, 7)
    names = list(LC)
    colors = np.array([LC[n] for n in names], np.uint8)
    cmap = colors[lab]
    out = cv2.addWeighted(img, 0.45, cmap, 0.55, 0)
    gsd = float(ctx.p("gsd", 0))
    pct = [float((lab == i).mean() * 100) for i in range(len(names))]
    for i, n in enumerate(names):
        ctx.stat(n.capitalize(), round(pct[i], 1), unit="%")
    if gsd:
        ha = img.shape[0] * img.shape[1] * gsd * gsd / 1e4
        ctx.table("Areas", ["Class", "%", "Hectares"], [[n, round(p, 1), round(p / 100 * ha, 2)] for n, p in zip(names, pct)], "land_cover.csv")
    else:
        ctx.table("Areas", ["Class", "%"], [[n, round(p, 1)] for n, p in zip(names, pct)], "land_cover.csv")
    if ctx.p("objects", False):
        r_ = ctx.predict("yolo26-obb", img, conf=0.25, imgsz=1024)[0]
        if r_.obb is not None and len(r_.obb):
            for p, c in zip(r_.obb.xyxyxyxy.cpu().numpy().astype(np.int32), r_.obb.cls.cpu().numpy().astype(int)):
                cv2.polylines(out, [p], True, WHITE, 2)
            ctx.stat("Objects", len(r_.obb))
    y = 10
    for n in names:
        cv2.rectangle(out, (10, y), (34, y + 24), LC[n], -1)
        cv2.putText(out, n, (42, y + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2, cv2.LINE_AA)
        y += 32
    ctx.add_image(out, "Land cover")
    ctx.chart("bar", "Land cover share", names, [{"name": "%", "values": [round(p, 1) for p in pct]}])
    ctx.note("Color indices from RGB imagery. With multispectral data (e.g. Sentinel-2 NIR) use NDVI/NDWI, or train SegFormer on labeled tiles for better accuracy.")


# ------------------------------------------------------------------ field boundaries

@pipeline("field_boundaries", "Crop field boundary detection",
          "Splits farmland imagery into individual fields and exports their outlines as GeoJSON.",
          IMAGE, [Param("gsd", "Ground resolution (m per pixel)", "number", 0, 0, 100, 0.1),
                  Param("min_area", "Smallest field (% of image)", "number", 0.4, 0.05, 20, 0.05),
                  Param("detail", "Boundary detail", "int", 14, 4, 40)])
def field_boundaries(ctx):
    img = fit(ctx.image(), 1400)
    sm = cv2.pyrMeanShiftFiltering(img, int(ctx.p("detail", 14)), 30)
    edges = cv2.Canny(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), 20, 60)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    roads = ((hsv[..., 1] < 35) & (hsv[..., 2] > 100)).astype(np.uint8) * 255
    barrier = cv2.dilate(edges | roads, np.ones((5, 5), np.uint8))
    free = (barrier == 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(free, 4)
    gsd = float(ctx.p("gsd", 0))
    out = img.copy()
    polys, rows = [], []
    for i in range(1, n):
        if stats[i][4] < float(ctx.p("min_area", 0.4)) / 100 * free.size:
            continue
        m = cv2.dilate((lab == i).astype(np.uint8), np.ones((5, 5), np.uint8))
        c = max(cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea)
        ap = cv2.approxPolyDP(c, 0.01 * cv2.arcLength(c, True), True)
        area_px = cv2.contourArea(ap)
        col = color_for(str(i))
        layer = out.copy()
        cv2.fillPoly(layer, [ap], col)
        out = cv2.addWeighted(layer, 0.35, out, 0.65, 0)
        cv2.polylines(out, [ap], True, WHITE, 2)
        fid = len(rows) + 1
        M = cv2.moments(ap)
        if M["m00"]:
            label(out, str(fid), int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]), AMBER)
        ha = area_px * gsd * gsd / 1e4 if gsd else None
        rows.append([fid, int(area_px), round(ha, 3) if ha else None, len(ap)])
        polys.append((ap, {"field": fid, "area_px": int(area_px), **({"area_ha": round(ha, 3)} if ha else {})}))
    ctx.add_image(out, "Fields")
    ctx.stat("Fields", len(rows))
    if gsd and rows:
        ctx.stat("Total area", round(sum(r[2] for r in rows), 2), unit="ha")
    ctx.table("Fields", ["Field", "Area (px)", "Area (ha)", "Vertices"], rows, "fields.csv")
    ctx.add_json(_geojson(polys, gsd or None), "fields.geojson")
    ctx.note("Classical segmentation. For production mapping, train a boundary model (e.g. U-Net on AI4Boundaries) and georeference with the image's GeoTIFF transform.")


# ------------------------------------------------------------------ building footprints

@pipeline("building_footprints", "Building footprint extraction",
          "Outlines buildings in aerial images with YOLOE-26 (or a classical roof detector) and exports polygons as GeoJSON.",
          IMAGE, [Param("prompts", "Look for", "text", "building, house, roof"),
                  Param("gsd", "Ground resolution (m per pixel)", "number", 0, 0, 100, 0.1),
                  Param("conf", "Confidence threshold", "number", 0.15, 0.05, 0.9, 0.05)],
          models=["yoloe26"], custom_task="segment")
def building_footprints(ctx):
    img = fit(ctx.image(), 1600)
    polys = []
    key = ctx.params.get("model")
    if isinstance(key, str) and key.startswith("custom:"):
        r = ctx.predict(key, img, conf=float(ctx.p("conf", 0.15)))[0]
    else:
        r = ctx.yoloe(prompts_list(ctx.p("prompts")), img, conf=float(ctx.p("conf", 0.15)))[0]
    for m in masks_of(r, img.shape):
        cs = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        if cs:
            polys.append(max(cs, key=cv2.contourArea))
    method = "YOLOE-26"
    if not polys:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        roof = ((hsv[..., 1] < 40) & (hsv[..., 2] > 160)).astype(np.uint8)
        roof = cv2.morphologyEx(roof, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        for c in cv2.findContours(roof, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            a = cv2.contourArea(c)
            (_, _), (w, h), _ = cv2.minAreaRect(c)
            if 80 < a < 0.05 * roof.size and a / max(w * h, 1) > 0.7 and max(w, h) / max(1, min(w, h)) < 5:
                polys.append(c)
        method = "classical roof detector"
    gsd = float(ctx.p("gsd", 0))
    out = img.copy()
    feats, rows = [], []
    for i, c in enumerate(polys, 1):
        rect = cv2.minAreaRect(c)
        simple = cv2.boxPoints(rect).astype(np.int32) if cv2.contourArea(c) / max(rect[1][0] * rect[1][1], 1) > 0.8 else cv2.approxPolyDP(c, 2, True)
        a = cv2.contourArea(simple)
        cv2.polylines(out, [simple], True, AMBER, 2)
        layer = out.copy()
        cv2.fillPoly(layer, [simple], AMBER)
        out = cv2.addWeighted(layer, 0.25, out, 0.75, 0)
        rows.append([i, int(a), round(a * gsd * gsd, 1) if gsd else None, len(simple)])
        feats.append((simple, {"building": i, "area_px": int(a), **({"area_m2": round(a * gsd * gsd, 1)} if gsd else {})}))
    ctx.add_image(out, "Building footprints")
    ctx.stat("Buildings", len(rows))
    ctx.stat("Method", method)
    if gsd and rows:
        ctx.stat("Built area", round(sum(r[2] for r in rows)), unit="m²")
    ctx.table("Buildings", ["#", "Area (px)", "Area (m²)", "Vertices"], rows, "buildings.csv")
    ctx.add_json(_geojson(feats, gsd or None), "buildings.geojson")
    ctx.note("For city-scale accuracy, fine-tune YOLO26-seg on building datasets such as SpaceNet or Inria Aerial and upload the weights.")


# ------------------------------------------------------------------ floor plans

@pipeline("floor_plan", "Floor plan understanding",
          "Finds walls, doors and rooms in a floor plan, reads room labels and computes room areas.",
          IMAGE, [Param("m_per_px", "Scale (meters per pixel)", "number", 0.01, 0.0001, 10, 0.0005),
                  Param("door", "Largest door opening (px)", "int", 130, 10, 400),
                  Param("read_labels", "Read room names (OCR)", "bool", True)],
          models=["easyocr"])
def floor_plan(ctx):
    img = fit(ctx.image(), 1800)
    g = to_gray(img)
    dark = (g < 110).astype(np.uint8)
    dist = cv2.distanceTransform(dark, cv2.DIST_L2, 3)
    wall_t = 2 * float(np.percentile(dist[dist > 0], 97)) if (dist > 0).any() else 8   # thickest strokes = walls
    thick = max(3, int(wall_t * 0.7))
    walls = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((thick, thick), np.uint8))   # keeps thick strokes, drops text
    gap = int(ctx.p("door", 130))
    closed = walls.copy()
    for k in (cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 1)), cv2.getStructuringElement(cv2.MORPH_RECT, (1, gap))):
        closed |= cv2.morphologyEx(walls, cv2.MORPH_CLOSE, k)
    doors = closed & (1 - walls)
    nd, dl, dstats, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(doors, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), 8)
    door_boxes = [dstats[i] for i in range(1, nd) if dstats[i][4] > thick * 5]
    free = (closed == 0).astype(np.uint8)
    n, lab, stats, cents = cv2.connectedComponentsWithStats(free, 4)
    H, W = free.shape
    names = []
    if ctx.p("read_labels", True):
        from .ocr import ocr_lines
        names = [(w["text"], ((w["box"][0] + w["box"][2]) / 2, (w["box"][1] + w["box"][3]) / 2))
                 for l in ocr_lines(ctx.ocr(img, ("en",))) for w in l["words"]]
    mpp = float(ctx.p("m_per_px", 0.01))
    out = img.copy()
    rows = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H or a < 0.005 * free.size:
            continue  # outside the building or tiny
        m = lab == i
        col = color_for(str(i))
        out[m] = (out[m] * 0.5 + np.array(col) * 0.5).astype(np.uint8)
        inside = [t for t, (cx, cy) in names if 0 <= int(cy) < H and 0 <= int(cx) < W and lab[int(cy), int(cx)] == i]
        name = " ".join(inside) if inside else f"Room {len(rows) + 1}"
        rows.append([len(rows) + 1, name, round(a * mpp * mpp, 2), int(a)])
        label(out, f"{name} {a * mpp * mpp:.1f} m²", int(cents[i][0]) - 40, int(cents[i][1]) + 30, AMBER)
    out[walls > 0] = (40, 40, 40)
    for x, y, w, h, a in door_boxes:
        cv2.rectangle(out, (x - 3, y - 3), (x + w + 3, y + h + 3), RED, 3)
    ctx.add_image(out, "Rooms, walls and doors (red)")
    ctx.stat("Rooms", len(rows))
    ctx.stat("Doors / openings", len(door_boxes))
    ctx.stat("Total floor area", round(sum(r[2] for r in rows), 1), unit="m²")
    ctx.table("Rooms", ["#", "Name", "Area (m²)", "Area (px)"], rows, "rooms.csv")
    ctx.note("Set the scale from a known dimension on the plan. Thin walls or hatched fills may need a trained segmentation model.")
