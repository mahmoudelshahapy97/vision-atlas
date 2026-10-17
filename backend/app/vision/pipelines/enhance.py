"""Image enhancement and restoration: low light, deblur, Real-ESRGAN, LaMa inpainting, restoration, colorization, depth."""
from __future__ import annotations

import cv2
import numpy as np

from ..core import AMBER, IMAGE, Param, UserError, banner, boxes_of, fit, masks_of, norm_points, pipeline
from ..registry import ModelError, manager
from .common import filter_classes, prompts_list, to_gray


def side_by_side(a: np.ndarray, b: np.ndarray, la: str = "Before", lb: str = "After") -> np.ndarray:
    h = min(a.shape[0], b.shape[0], 900)
    ra = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h))
    rb = cv2.resize(b, (int(b.shape[1] * h / b.shape[0]), h))
    out = cv2.hconcat([ra, np.full((h, 8, 3), 255, np.uint8), rb])
    for x, t in ((10, la), (ra.shape[1] + 18, lb)):
        cv2.putText(out, t, (x, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(out, t, (x, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def sharpness(img) -> float:
    return float(cv2.Laplacian(to_gray(img), cv2.CV_64F).var())


# ------------------------------------------------------------------ low light

@pipeline("low_light", "Low-light enhancement",
          "Brightens dark photos with adaptive contrast (CLAHE), automatic gamma and optional denoising.",
          IMAGE, [Param("clip", "Contrast strength", "number", 2.5, 1, 6, 0.5),
                  Param("target", "Target brightness", "number", 0.45, 0.2, 0.7, 0.05),
                  Param("denoise", "Denoise strength", "int", 6, 0, 20, 1)])
def low_light(ctx):
    img = ctx.image()
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = lab[..., 0].astype(np.float32) / 255
    mean = max(L.mean(), 1e-3)
    gamma = float(np.clip(np.log(float(ctx.p("target", 0.45))) / np.log(mean), 0.25, 1.5))
    L = np.power(L, gamma)
    lab[..., 0] = cv2.createCLAHE(clipLimit=float(ctx.p("clip", 2.5)), tileGridSize=(8, 8)).apply((L * 255).astype(np.uint8))
    out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    d = int(ctx.p("denoise", 6))
    if d > 0:
        out = cv2.fastNlMeansDenoisingColored(out, None, d, d, 7, 21)
    ctx.add_image(side_by_side(img, out), "Before / after")
    ctx.add_image(out, "Enhanced")
    ctx.stat("Brightness before", round(float(to_gray(img).mean() / 255 * 100)), unit="%")
    ctx.stat("Brightness after", round(float(to_gray(out).mean() / 255 * 100)), unit="%")
    ctx.stat("Gamma applied", round(gamma, 2))
    ctx.note("Classical enhancement. Learned models such as Zero-DCE handle extreme darkness and color casts better.")


# ------------------------------------------------------------------ deblur

def _psf(shape, kind, length, angle, sigma):
    h, w = shape
    psf = np.zeros((h, w), np.float32)
    c = (w // 2, h // 2)
    if kind == "motion":
        a = np.deg2rad(angle)
        dx, dy = np.cos(a) * length / 2, -np.sin(a) * length / 2
        cv2.line(psf, (int(c[0] - dx), int(c[1] - dy)), (int(c[0] + dx), int(c[1] + dy)), 1.0, 1, cv2.LINE_AA)
    else:
        k = cv2.getGaussianKernel(int(sigma * 6) | 1, sigma)
        kk = (k @ k.T).astype(np.float32)
        y0, x0 = c[1] - kk.shape[0] // 2, c[0] - kk.shape[1] // 2
        psf[y0:y0 + kk.shape[0], x0:x0 + kk.shape[1]] = kk
    return psf / max(psf.sum(), 1e-6)


@pipeline("deblur", "Image deblurring",
          "Reverses motion or focus blur with Wiener deconvolution. Set the blur length and angle you see in the photo.",
          IMAGE, [Param("kind", "Blur type", "select", "motion", options=["motion", "out of focus"]),
                  Param("length", "Motion length (px)", "int", 21, 3, 80),
                  Param("angle", "Motion angle (°)", "number", 0, -90, 90, 1),
                  Param("sigma", "Focus blur size", "number", 2.5, 0.5, 10, 0.5),
                  Param("noise", "Noise level", "number", 0.008, 0.001, 0.1, 0.001)])
def deblur(ctx):
    img = ctx.image()
    work = fit(img, 1600)
    pad = 40
    padded = cv2.copyMakeBorder(work, pad, pad, pad, pad, cv2.BORDER_REFLECT)
    kind = "motion" if ctx.p("kind", "motion") == "motion" else "gaussian"
    psf = _psf(padded.shape[:2], kind, int(ctx.p("length", 21)), float(ctx.p("angle", 0)), float(ctx.p("sigma", 2.5)))
    H = np.fft.fft2(np.fft.ifftshift(psf))
    K = float(ctx.p("noise", 0.008))
    Wf = np.conj(H) / (np.abs(H) ** 2 + K)
    out = np.zeros_like(padded, np.float32)
    for c in range(3):
        G = np.fft.fft2(padded[..., c].astype(np.float32) / 255)
        out[..., c] = np.real(np.fft.ifft2(G * Wf))
    out = np.clip(out[pad:-pad, pad:-pad] * 255, 0, 255).astype(np.uint8)
    out = cv2.bilateralFilter(out, 5, 30, 5)
    ctx.add_image(side_by_side(work, out), "Before / after")
    ctx.add_image(out, "Deblurred")
    ctx.stat("Sharpness before", round(sharpness(work)))
    ctx.stat("Sharpness after", round(sharpness(out)), "good")
    ctx.note("If you see ringing, raise the noise level or adjust the blur length. Learned models (Restormer, DeblurGAN-v2) handle unknown blur better.")


# ------------------------------------------------------------------ super-resolution (Real-ESRGAN)

def esrgan(img: np.ndarray, tile: int = 256, overlap: int = 16, progress=None) -> np.ndarray:
    """4x upscale, one overlapping tile per request so progress keeps moving."""
    with manager.use("realesrgan") as net:
        H, W = img.shape[:2]
        out = np.zeros((H * 4, W * 4, 3), np.uint8)
        tiles = [(y, x0) for y in range(0, H, tile) for x0 in range(0, W, tile)]
        for n, (y, x0) in enumerate(tiles):
            y1, x1 = max(0, y - overlap), max(0, x0 - overlap)
            y2, x2 = min(H, y + tile + overlap), min(W, x0 + tile + overlap)
            o = net.upscale(img[y1:y2, x1:x2])
            oy, ox = (y - y1) * 4, (x0 - x1) * 4
            th, tw = min(tile, H - y) * 4, min(tile, W - x0) * 4
            out[y * 4:y * 4 + th, x0 * 4:x0 * 4 + tw] = o[oy:oy + th, ox:ox + tw]
            if progress:
                progress((n + 1) / len(tiles))
    return out


@pipeline("super_resolution", "Image super-resolution (Real-ESRGAN)",
          "Upscales images 2× or 4× and recovers detail with the public Real-ESRGAN general model.",
          IMAGE, [Param("scale", "Upscale", "select", 4, options=[2, 4]),
                  Param("max_side", "Limit input size (px)", "select", 512, options=[256, 384, 512, 768, 1024],
                        help="Larger inputs take much longer on CPU.")],
          models=["realesrgan"])
def super_resolution(ctx):
    img = ctx.image()
    limit = int(ctx.p("max_side", 512))
    src = fit(img, limit)
    if src.shape != img.shape:
        ctx.note(f"Input was reduced to {src.shape[1]}×{src.shape[0]} first to keep CPU time reasonable.")
    out = esrgan(src, progress=ctx.progress)
    if int(ctx.p("scale", 4)) == 2:
        out = cv2.resize(out, (src.shape[1] * 2, src.shape[0] * 2), interpolation=cv2.INTER_AREA)
    bicubic = cv2.resize(src, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_CUBIC)
    h, w = out.shape[:2]
    cy, cx, ch, cw = h // 3, w // 3, h // 3, w // 3
    ctx.add_image(side_by_side(bicubic[cy:cy + ch, cx:cx + cw], out[cy:cy + ch, cx:cx + cw], "Bicubic", "Real-ESRGAN"), "Zoomed comparison")
    ctx.add_png(out, "Upscaled")
    ctx.stat("Input", f"{src.shape[1]}×{src.shape[0]}")
    ctx.stat("Output", f"{out.shape[1]}×{out.shape[0]}", "good")
    ctx.stat("Sharpness gain", round(sharpness(out) / max(sharpness(bicubic), 1e-6), 2), unit="×")


# ------------------------------------------------------------------ inpainting (LaMa)

def inpaint(img: np.ndarray, mask: np.ndarray, max_side: int = 1024) -> tuple[np.ndarray, str]:
    """Fill mask>0 regions. Uses LaMa when available, OpenCV Telea otherwise."""
    if not mask.any():
        return img.copy(), "none"
    try:
        h, w = img.shape[:2]
        s = min(1.0, max_side / max(h, w))
        im = cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img
        mk = cv2.resize(mask, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST) if s < 1 else mask
        ph, pw = (8 - im.shape[0] % 8) % 8, (8 - im.shape[1] % 8) % 8
        imp = cv2.copyMakeBorder(im, 0, ph, 0, pw, cv2.BORDER_REFLECT)
        mkp = cv2.copyMakeBorder(mk, 0, ph, 0, pw, cv2.BORDER_CONSTANT, value=0)
        with manager.use("lama") as net:
            res = net.inpaint(imp, mkp)
        res = res[:im.shape[0], :im.shape[1]]
        if s < 1:
            res = cv2.resize(res, (w, h), interpolation=cv2.INTER_CUBIC)
        m3 = cv2.GaussianBlur((mask > 0).astype(np.float32), (7, 7), 0)[..., None]
        return (img * (1 - m3) + res * m3).astype(np.uint8), "LaMa"
    except ModelError:
        raise
    except Exception:
        return cv2.inpaint(img, (mask > 0).astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA), "OpenCV Telea"


@pipeline("object_removal", "Intelligent object removal",
          "Removes the objects you pick (by class, by description, or by drawing a box) and fills the background with LaMa.",
          IMAGE, [Param("classes", "Remove these classes (YOLO26)", "multiselect", ["person"], options=["person", "car", "bicycle", "motorcycle", "bus", "truck", "dog", "cat", "bird", "bottle", "chair", "backpack", "handbag", "suitcase", "umbrella"]),
                  Param("prompts", "…or describe what to remove (YOLOE-26)", "text", "", help="e.g. 'trash can, sign'"),
                  Param("box", "…or draw a box", "box", None),
                  Param("grow", "Grow mask (px)", "int", 12, 0, 60)],
          models=["yolo26-segment", "yoloe26", "lama"])
def object_removal(ctx):
    img = ctx.image()
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    removed = []
    if ctx.p("box"):
        pts = norm_points(ctx.p("box"), w, h)
        if len(pts) >= 2:
            x1, y1 = pts.min(0)
            x2, y2 = pts.max(0)
            mask[max(0, y1):y2, max(0, x1):x2] = 1
            removed.append("drawn area")
    prompts = prompts_list(ctx.p("prompts"))
    if prompts:
        r = ctx.yoloe(prompts, img, conf=0.2)[0]
        for m in masks_of(r, img.shape):
            mask |= m
        removed += [d["cls"] for d in boxes_of(r)]
    elif not ctx.p("box") and ctx.p("classes"):
        r = ctx.predict("yolo26-segment", img, conf=0.3)[0]
        dets = filter_classes(boxes_of(r), ctx.p("classes"))
        ms = masks_of(r, img.shape)
        for d in dets:
            mask |= ms[d["i"]]
        removed += [d["cls"] for d in dets]
    if not mask.any():
        raise UserError("Nothing to remove was found. Pick a class, describe the object, or draw a box.")
    g = int(ctx.p("grow", 12))
    if g:
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    out, method = inpaint(img, mask)
    vis = img.copy()
    vis[mask > 0] = (vis[mask > 0] * 0.4 + np.array(AMBER) * 0.6).astype(np.uint8)
    ctx.add_image(side_by_side(vis, out, "Mask", "Result"), "Mask / result")
    ctx.add_image(out, "Result")
    ctx.stat("Objects removed", len(removed))
    ctx.stat("Area filled", round(float(mask.mean() * 100), 1), unit="%")
    ctx.stat("Fill method", method)


# ------------------------------------------------------------------ old photo restoration

@pipeline("photo_restoration", "Old photo restoration",
          "Finds scratches and dust spots, fills them with LaMa, then reduces noise and restores contrast.",
          IMAGE, [Param("sensitivity", "Scratch sensitivity", "int", 30, 5, 80),
                  Param("contrast", "Restore contrast", "bool", True)],
          models=["lama"])
def photo_restoration(ctx):
    img = ctx.image()
    g = to_gray(img)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    bright = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, k)
    dark = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k)
    s = int(ctx.p("sensitivity", 30))
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thin_bright = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, k5)
    thin_dark = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k5)
    cand = ((thin_bright > s * 0.5) | (thin_dark > s + 20)).astype(np.uint8)
    # scratches: long thin runs in any direction (directional openings keep only line-like structures)
    L = max(40, img.shape[0] // 12)
    lines = np.zeros_like(cand)
    for ang in (0, 30, 60, 90, 120, 150):
        k = np.zeros((L, L), np.uint8)
        c = L // 2
        dx, dy = np.cos(np.deg2rad(ang)) * c, np.sin(np.deg2rad(ang)) * c
        cv2.line(k, (int(c - dx), int(c - dy)), (int(c + dx), int(c + dy)), 1, 1)
        lines |= cv2.morphologyEx(cand, cv2.MORPH_OPEN, k)
    # dust: small isolated specks
    specks = np.zeros_like(cand)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(((bright > s) | (dark > s + 25)).astype(np.uint8), 8)
    small = np.where((stats[:, cv2.CC_STAT_AREA] < 120) & (stats[:, cv2.CC_STAT_WIDTH] <= 14) & (stats[:, cv2.CC_STAT_HEIGHT] <= 14))[0]
    specks[np.isin(lab, small[small > 0])] = 1
    keep = cv2.dilate(lines | specks, np.ones((3, 3), np.uint8), iterations=2)
    fixed, method = inpaint(img, keep)
    fixed = cv2.fastNlMeansDenoisingColored(fixed, None, 5, 5, 7, 21)
    if ctx.p("contrast", True):
        lab_ = cv2.cvtColor(fixed, cv2.COLOR_BGR2LAB)
        lab_[..., 0] = cv2.createCLAHE(2.0, (8, 8)).apply(lab_[..., 0])
        fixed = cv2.cvtColor(lab_, cv2.COLOR_LAB2BGR)
    vis = img.copy()
    vis[keep > 0] = (0, 0, 255)
    ctx.add_image(side_by_side(img, fixed), "Before / after")
    ctx.add_image(vis, "Detected damage (red)")
    ctx.add_image(fixed, "Restored")
    ctx.stat("Damaged area", round(float(keep.mean() * 100), 2), unit="%")
    ctx.stat("Fill method", method)


# ------------------------------------------------------------------ colorization

@pipeline("colorization", "Black-and-white colorization",
          "Predicts plausible colors for grayscale photos with the Colorful Image Colorization model (Zhang et al.).",
          IMAGE, [Param("saturation", "Color strength", "number", 1.0, 0.3, 2.0, 0.1)], models=["colorization"])
def colorization(ctx):
    img = ctx.image()
    lab = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    L = lab[..., 0]
    small = cv2.resize(L, (256, 256))
    with manager.use("colorization") as net:
        ab = net.ab(small)
    ab = cv2.resize(ab, (img.shape[1], img.shape[0])) * float(ctx.p("saturation", 1.0))
    out = cv2.cvtColor(np.dstack([L, ab]).astype(np.float32), cv2.COLOR_LAB2BGR)
    out = np.clip(out * 255, 0, 255).astype(np.uint8)
    ctx.add_image(side_by_side(img, out), "Before / after")
    ctx.add_image(out, "Colorized")
    ctx.stat("Mean saturation", round(float(cv2.cvtColor(out, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255 * 100)), unit="%")
    ctx.note("Colors are a plausible guess, not a record of the original scene.")


# ------------------------------------------------------------------ depth (MiDaS)

def midas_depth(img: np.ndarray) -> np.ndarray:
    """Relative inverse depth (bigger = closer), same size as img."""
    with manager.use("midas") as net:
        return net.depth(img)


@pipeline("depth_estimation", "Monocular depth estimation",
          "Estimates relative depth from a single photo with MiDaS and ranks detected objects from nearest to farthest.",
          IMAGE, [Param("objects", "Rank detected objects by distance", "bool", True)], models=["midas", "yolo26-detect"])
def depth_estimation(ctx):
    img = fit(ctx.image(), 1280)
    d = midas_depth(img)
    dn = (d - d.min()) / (np.ptp(d) + 1e-6)
    color = cv2.applyColorMap((dn * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    ctx.add_image(side_by_side(img, color, "Photo", "Depth (bright = near)"), "Depth map")
    rows = []
    if ctx.p("objects", True):
        dets = boxes_of(ctx.predict("yolo26-detect", img, conf=0.3)[0])
        vis = img.copy()
        for det in dets:
            x1, y1, x2, y2 = map(int, det["box"])
            region = dn[max(0, y1):y2, max(0, x1):x2]
            if region.size:
                det["near"] = float(np.median(region))
        dets = sorted([x for x in dets if "near" in x], key=lambda x: -x["near"])
        for rank, det in enumerate(dets, 1):
            from ..core import box
            box(vis, det["box"], f"#{rank} {det['cls']}", AMBER)
            rows.append([rank, det["cls"], round(det["near"], 3), round(det["conf"], 2)])
        if dets:
            ctx.add_image(vis, "Objects ranked nearest first")
    depth16 = (dn * 65535).astype(np.uint16)
    ok, png = cv2.imencode(".png", depth16)
    ctx.add_file(png.tobytes(), "depth_16bit.png")
    ctx.stat("Objects ranked", len(rows))
    if rows:
        ctx.stat("Nearest object", rows[0][1])
        ctx.table("Objects by distance", ["Rank", "Object", "Nearness (0–1)", "Detection conf"], rows, "depth_objects.csv")
    ctx.note("MiDaS gives relative depth. For distances in meters, use a metric model (e.g. Depth Anything V2 Metric) or calibrate with a known object.")
