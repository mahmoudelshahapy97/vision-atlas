"""Document geometry and optical reading: scanner, barcodes/QR, bubble sheets, analog gauges."""
from __future__ import annotations

import math

import cv2
import numpy as np

from ..core import AMBER, GREEN, IMAGE, RED, WHITE, BLUE, Param, UserError, banner, box, label, pipeline
from .common import to_gray


# ------------------------------------------------------------------ page detection (shared)

def order_quad(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def find_page(img: np.ndarray, min_area: float = 0.15) -> np.ndarray | None:
    """Corners (tl, tr, br, bl) of the largest page-like quadrilateral, or None."""
    h, w = img.shape[:2]
    s = 1000 / max(h, w)
    small = cv2.resize(img, (int(w * s), int(h * s)))
    g = cv2.GaussianBlur(to_gray(small), (5, 5), 0)
    cands = []
    edges = cv2.dilate(cv2.Canny(g, 40, 140), np.ones((3, 3), np.uint8), iterations=2)
    _, bright = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    for m in (edges, bright):
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < min_area * small.shape[0] * small.shape[1]:
                continue
            peri = cv2.arcLength(c, True)
            for eps in (0.02, 0.03, 0.05):
                ap = cv2.approxPolyDP(c, eps * peri, True)
                if len(ap) == 4 and cv2.isContourConvex(ap):
                    cands.append((area, ap.reshape(4, 2)))
                    break
            else:
                hull = cv2.convexHull(c)
                if cv2.contourArea(hull) > 0 and area / cv2.contourArea(hull) > 0.9:
                    cands.append((area * 0.9, cv2.boxPoints(cv2.minAreaRect(c))))
    if not cands:
        return None
    area, quad = max(cands, key=lambda c: c[0])
    if area > 0.97 * small.shape[0] * small.shape[1]:
        return None  # the "page" is the whole frame: already a flat scan
    return order_quad(np.asarray(quad, np.float32) / s)


def warp_page(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    W = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    H = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    M = cv2.getPerspectiveTransform(quad, np.float32([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]]))
    return cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_CUBIC)


def flatten_light(img: np.ndarray) -> np.ndarray:
    """Remove shadows and uneven lighting by dividing by a smooth background estimate."""
    out = []
    for ch in cv2.split(img):
        bg = cv2.medianBlur(cv2.dilate(ch, np.ones((7, 7), np.uint8)), 31)
        out.append(cv2.normalize(255 - cv2.absdiff(ch, bg), None, 0, 255, cv2.NORM_MINMAX))
    return cv2.merge(out)


def scan(img: np.ndarray, mode: str = "color") -> tuple[np.ndarray, np.ndarray | None]:
    quad = find_page(img)
    page = warp_page(img, quad) if quad is not None else img.copy()
    if mode == "bw":
        g = to_gray(flatten_light(page))
        page = cv2.cvtColor(cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12), cv2.COLOR_GRAY2BGR)
    elif mode == "color":
        page = flatten_light(page)
    elif mode == "gray":
        page = cv2.cvtColor(to_gray(flatten_light(page)), cv2.COLOR_GRAY2BGR)
    return page, quad


def draw_quad(img, quad):
    out = img.copy()
    if quad is not None:
        cv2.polylines(out, [quad.astype(np.int32)], True, AMBER, max(3, img.shape[1] // 300), cv2.LINE_AA)
        for p in quad:
            cv2.circle(out, tuple(map(int, p)), max(8, img.shape[1] // 120), AMBER, -1, cv2.LINE_AA)
    return out


# ------------------------------------------------------------------ document scanner

@pipeline("document_scanner", "Smart document scanner",
          "Finds the page edges, flattens the perspective, removes shadows and outputs a clean scan.",
          IMAGE, [Param("mode", "Output", "select", "color", options=["color", "gray", "bw", "original"])])
def document_scanner(ctx):
    img = ctx.image()
    page, quad = scan(img, ctx.p("mode", "color"))
    ctx.add_image(page, "Scanned page")
    ctx.add_image(draw_quad(img, quad), "Detected page edges")
    ctx.stat("Page found", "yes" if quad is not None else "no — used the full image", "good" if quad is not None else "warn")
    ctx.stat("Output size", f"{page.shape[1]}×{page.shape[0]}")
    ok, png = cv2.imencode(".png", page)
    ctx.add_file(png.tobytes(), "scan.png")
    try:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB)).save(buf, "PDF", resolution=200)
        ctx.add_file(buf.getvalue(), "scan.pdf")
    except Exception:
        pass
    if quad is None:
        ctx.note("Couldn't find the page edges. Photograph the page against a darker, plain surface with all four corners visible.")


# ------------------------------------------------------------------ barcodes and QR codes

def _ean_ok(code: str) -> bool | None:
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return None
    d = [int(c) for c in code]
    if len(d) == 12:  # UPC-A
        return (3 * sum(d[0:11:2]) + sum(d[1:11:2]) + d[11]) % 10 == 0
    body, check = d[:-1], d[-1]
    weights = [1, 3] * 6 if len(d) == 13 else [3, 1] * 4
    return (10 - sum(a * b for a, b in zip(body, weights)) % 10) % 10 == check


@pipeline("barcode_reader", "Barcode and QR code reader",
          "Finds and decodes QR codes and 1D barcodes (EAN, UPC, Code128 …), including rotated or small ones, and validates checksums.",
          IMAGE, [Param("try_harder", "Try rotations and upscaling", "bool", True)])
def barcode_reader(ctx):
    img = ctx.image()
    found = []

    def add(kind, text, pts, variant):
        if not text:
            return
        if any(f[1] == text for f in found):
            return
        found.append((kind, text, pts, variant))

    variants = [("original", img, None)]
    if ctx.p("try_harder", True):
        h, w = img.shape[:2]
        if max(h, w) < 1600:
            variants.append(("2× upscaled", cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC), 2.0))
        variants.append(("sharpened", cv2.addWeighted(img, 1.6, cv2.GaussianBlur(img, (0, 0), 3), -0.6, 0), None))
    qr = cv2.QRCodeDetector()
    bd = cv2.barcode.BarcodeDetector() if hasattr(cv2, "barcode") else None
    for name, v, scale in variants:
        try:
            ok, texts, pts, _ = qr.detectAndDecodeMulti(v)
            if ok:
                for t, p in zip(texts, pts):
                    add("QR", t, p / (scale or 1), name)
        except cv2.error:
            pass
        if bd is not None:
            try:
                res = bd.detectAndDecodeWithType(v)
                ok, texts, types, pts = (True, *res) if len(res) == 3 else res
                for t, ty, p in zip(texts or [], types or [], pts if pts is not None else []):
                    add(ty or "barcode", t, p / (scale or 1), name)
            except (cv2.error, ValueError, TypeError):
                try:
                    ok, texts, types, pts = bd.detectAndDecodeMulti(v)
                    for t, ty, p in zip(texts or [], types or [], pts if pts is not None else []):
                        add(ty or "barcode", t, p / (scale or 1), name)
                except cv2.error:
                    pass
    out = img.copy()
    rows = []
    for kind, text, pts, variant in found:
        p = np.asarray(pts, np.float32).reshape(-1, 2).astype(np.int32)
        cv2.polylines(out, [p], True, GREEN, max(3, img.shape[1] // 250), cv2.LINE_AA)
        label(out, f"{kind}: {text[:40]}", int(p[:, 0].min()), int(p[:, 1].min()), GREEN, WHITE)
        chk = _ean_ok(text)
        rows.append([kind, text, {True: "valid", False: "INVALID", None: "n/a"}[chk],
                     "yes" if text.startswith(("http://", "https://")) else "no", variant])
    ctx.add_image(out, "Decoded codes")
    ctx.stat("Codes found", len(found), "good" if found else "warn")
    if rows:
        ctx.table("Codes", ["Type", "Content", "Checksum", "Link", "Found in"], rows, "codes.csv")
        if any(r[2] == "INVALID" for r in rows):
            ctx.note("At least one barcode failed its checksum, so it may be misprinted or misread.")
    else:
        ctx.note("No codes decoded. Move closer, avoid glare, and keep the code flat and in focus.")


# ------------------------------------------------------------------ OMR answer sheets

@pipeline("omr_grading", "Exam sheet grading (OMR)",
          "Reads filled bubbles on a multiple-choice sheet and grades them against your answer key.",
          IMAGE, [Param("key", "Answer key", "text", "B,E,A,D,B,C,A,E", help="One letter per question, comma-separated."),
                  Param("options", "Choices per question", "int", 5, 2, 8),
                  Param("fill", "Filled if darker than (%)", "int", 45, 15, 90)])
def omr_grading(ctx):
    img = ctx.image()
    key = [k.strip().upper() for k in str(ctx.p("key", "")).split(",") if k.strip()]
    n_opt = int(ctx.p("options", 5))
    fill = float(ctx.p("fill", 45)) / 100
    page, quad = scan(img, "original")
    g = cv2.GaussianBlur(to_gray(page), (5, 5), 0)
    th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = page.shape[:2]
    bubbles = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        ar = w / float(h)
        if 0.75 <= ar <= 1.3 and W * 0.025 <= w <= W * 0.15:
            bubbles.append((x, y, w, h))
    if len(bubbles) < n_opt:
        raise UserError("Couldn't find the answer bubbles. Photograph the whole sheet flat, with good light.")
    # keep the dominant bubble size, then group into rows
    med = np.median([b[2] for b in bubbles])
    bubbles = sorted([b for b in bubbles if 0.7 * med <= b[2] <= 1.4 * med], key=lambda b: b[1])
    rows_, cur = [], [bubbles[0]]
    for b in bubbles[1:]:
        if abs(b[1] - cur[-1][1]) < med * 0.6:
            cur.append(b)
        else:
            rows_.append(cur)
            cur = [b]
    rows_.append(cur)
    rows_ = [sorted(r, key=lambda b: b[0])[-n_opt:] for r in rows_ if len(r) >= n_opt]
    out = page.copy()
    results, correct = [], 0
    for q, row in enumerate(rows_):
        ratios = []
        for (x, y, w, h) in row:
            m = np.zeros(th.shape, np.uint8)
            cv2.circle(m, (x + w // 2, y + h // 2), int(min(w, h) * 0.38), 255, -1)
            ratios.append(cv2.countNonZero(cv2.bitwise_and(th, th, mask=m)) / max(1, cv2.countNonZero(m)))
        marked = [i for i, r in enumerate(ratios) if r >= fill]
        answer = "".join("ABCDEFGH"[i] for i in marked) or "-"
        expected = key[q] if q < len(key) else None
        ok = expected is not None and answer == expected
        correct += ok
        for i, (x, y, w, h) in enumerate(row):
            c = (x + w // 2, y + h // 2)
            if i in marked:
                cv2.circle(out, c, int(w * 0.55), GREEN if ok else RED, 4, cv2.LINE_AA)
            elif expected and "ABCDEFGH"[i] == expected:
                cv2.circle(out, c, int(w * 0.55), BLUE, 3, cv2.LINE_AA)
        status = "correct" if ok else ("blank" if not marked else "multiple" if len(marked) > 1 else "wrong") if expected else "no key"
        results.append([q + 1, answer, expected or "", status, ", ".join(f"{r:.0%}" for r in ratios)])
    total = min(len(rows_), len(key)) if key else len(rows_)
    score = round(correct / total * 100) if total else 0
    banner(out, [f"Score: {correct}/{total} ({score}%)"])
    ctx.add_image(out, "Graded sheet")
    ctx.stat("Score", f"{correct}/{total}", "good" if score >= 50 else "bad")
    ctx.stat("Percent", score, unit="%")
    ctx.stat("Questions read", len(rows_))
    ctx.table("Answers", ["Question", "Marked", "Key", "Result", "Fill per choice"], results, "grades.csv")
    if key and len(rows_) != len(key):
        ctx.note(f"Found {len(rows_)} questions but the key has {len(key)} answers.")


# ------------------------------------------------------------------ analog gauges

@pipeline("gauge_reader", "Analog gauge reader",
          "Finds the dial and needle and converts the needle angle to a reading on the scale you enter.",
          IMAGE, [Param("min_value", "Value at the start of the scale", "number", 0, -1e6, 1e6, 1),
                  Param("max_value", "Value at the end of the scale", "number", 100, -1e6, 1e6, 1),
                  Param("min_angle", "Start angle (° clockwise from 12 o'clock)", "number", -135, -180, 180, 1),
                  Param("max_angle", "End angle (° clockwise from 12 o'clock)", "number", 135, -180, 360, 1),
                  Param("unit", "Unit", "text", "bar")])
def gauge_reader(ctx):
    img = ctx.image()
    h, w = img.shape[:2]
    s = 800 / max(h, w)
    small = cv2.resize(img, (int(w * s), int(h * s)))
    g = cv2.medianBlur(to_gray(small), 5)
    circles = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, 1.2, small.shape[0] / 2, param1=120, param2=40,
                               minRadius=int(min(small.shape[:2]) * 0.18), maxRadius=int(min(small.shape[:2]) * 0.52))
    if circles is None:
        raise UserError("Couldn't find a round dial. Photograph the gauge face-on and fill most of the frame.")
    cx, cy, r = max(circles[0], key=lambda c: c[2])
    # needle = the darkest / reddest ray between 15% and 55% of the radius
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    dark = 255 - g.astype(np.float32)
    red = ((hsv[..., 0] < 12) | (hsv[..., 0] > 165)).astype(np.float32) * hsv[..., 1]
    score_img = np.maximum(dark, red)
    angles = np.arange(0, 360, 0.5)
    prof = []
    for a in angles:
        rad = math.radians(a)
        rr = np.linspace(0.15 * r, 0.55 * r, 40)
        xs = np.clip((cx + rr * math.sin(rad)).astype(int), 0, small.shape[1] - 1)
        ys = np.clip((cy - rr * math.cos(rad)).astype(int), 0, small.shape[0] - 1)
        prof.append(score_img[ys, xs].mean())
    prof = np.convolve(np.r_[prof[-3:], prof, prof[:3]], np.ones(5) / 5, mode="same")[3:-3]
    a_needle = float(angles[int(np.argmax(prof))])          # clockwise from 12 o'clock, 0..360
    a0, a1 = float(ctx.p("min_angle", -135)), float(ctx.p("max_angle", 135))
    rel = (a_needle - a0) % 360
    span = (a1 - a0) % 360 or 360
    if rel > span:  # needle in the dead zone: snap to the nearest end
        rel = span if rel - span < 360 - rel else 0
    v0, v1 = float(ctx.p("min_value", 0)), float(ctx.p("max_value", 100))
    value = v0 + (v1 - v0) * rel / span
    unit = ctx.p("unit", "")
    out = img.copy()
    C = (int(cx / s), int(cy / s))
    R = r / s
    cv2.circle(out, C, int(R), AMBER, max(3, int(4 / s)), cv2.LINE_AA)
    tip = (int(C[0] + 0.9 * R * math.sin(math.radians(a_needle))), int(C[1] - 0.9 * R * math.cos(math.radians(a_needle))))
    cv2.line(out, C, tip, GREEN, max(4, int(5 / s)), cv2.LINE_AA)
    for a in (a0, a1):
        p = (int(C[0] + R * math.sin(math.radians(a))), int(C[1] - R * math.cos(math.radians(a))))
        cv2.circle(out, p, max(6, int(8 / s)), BLUE, -1, cv2.LINE_AA)
    banner(out, [f"Reading: {value:.1f} {unit}", f"Needle: {a_needle:.0f}°"])
    ctx.add_image(out, "Gauge reading")
    ctx.stat("Reading", f"{value:.1f} {unit}".strip(), "good")
    ctx.stat("Needle angle", round(a_needle, 1), unit="°")
    ctx.stat("Dial radius", round(R), unit="px")
    ctx.note("Blue dots mark where you said the scale starts and ends. Adjust the angles if they don't sit on the first and last ticks.")
