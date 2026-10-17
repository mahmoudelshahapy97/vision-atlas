"""Image forensics, multi-view 3D reconstruction and palmprint matching."""
from __future__ import annotations

import io
import math

import cv2
import numpy as np

from ..core import AMBER, GREEN, IMAGE, RED, WHITE, Param, Slot, UserError, banner, fit, pipeline
from .common import heatmap_overlay, to_gray


# ------------------------------------------------------------------ forgery

@pipeline("forgery_analysis", "Image forgery detection",
          "Looks for signs of editing: copy-move (a region duplicated inside the image) and error-level differences from re-compression.",
          IMAGE, [Param("min_matches", "Copy-move: matches needed", "int", 12, 4, 100),
                  Param("min_shift", "Copy-move: minimum distance (px)", "int", 40, 10, 500)])
def forgery_analysis(ctx):
    img = fit(ctx.image(), 1600)
    # Error level analysis
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    re = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
    ela = cv2.absdiff(img, re).max(axis=2).astype(np.float32)
    ela = cv2.GaussianBlur(ela, (0, 0), 4)
    # Copy-move with SIFT self-matching
    sift = cv2.SIFT_create(6000)
    kp, des = sift.detectAndCompute(to_gray(img), None)
    pairs = []
    if des is not None and len(kp) > 10:
        matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des, des, k=3)
        for ms in matches:
            for m in ms[1:]:  # ms[0] is the point itself
                p1, p2 = np.array(kp[m.queryIdx].pt), np.array(kp[m.trainIdx].pt)
                if m.distance < 0.5 * max(ms[-1].distance, 1e-6) or m.distance < 60:
                    if np.linalg.norm(p1 - p2) > int(ctx.p("min_shift", 40)):
                        pairs.append((p1, p2))
                    break
    # keep pairs that share a common displacement (a moved region moves as a whole)
    clusters: dict[tuple, list] = {}
    for p1, p2 in pairs:
        if (p2[0], p2[1]) < (p1[0], p1[1]):
            p1, p2 = p2, p1          # orient every pair the same way so A→B and B→A agree
        d = p2 - p1
        clusters.setdefault((int(d[0] // 16), int(d[1] // 16)), []).append((p1, p2))
    merged, seen = [], set()
    for k in sorted(clusters, key=lambda k: -len(clusters[k])):
        if k in seen:
            continue
        grp = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                kk = (k[0] + dx, k[1] + dy)
                if kk in clusters and kk not in seen:
                    grp += clusters[kk]
                    seen.add(kk)
        merged.append(grp)
    groups = [g for g in merged if len(g) >= int(ctx.p("min_matches", 12))]
    out = img.copy()
    rows = []
    for gi, g in enumerate(sorted(groups, key=len, reverse=True)[:5]):
        a = np.array([p for p, _ in g])
        b = np.array([q for _, q in g])
        for p, q in g[:150]:
            cv2.line(out, tuple(map(int, p)), tuple(map(int, q)), AMBER, 1, cv2.LINE_AA)
        for pts, col in ((a, GREEN), (b, RED)):
            x1, y1 = pts.min(0).astype(int)
            x2, y2 = pts.max(0).astype(int)
            cv2.rectangle(out, (x1 - 8, y1 - 8), (x2 + 8, y2 + 8), col, 3)
        shift = np.median(b - a, axis=0)
        rows.append([gi + 1, len(g), f"({shift[0]:.0f}, {shift[1]:.0f})", f"{a.min(0).astype(int).tolist()}–{a.max(0).astype(int).tolist()}"])
    ela_ratio = float(ela.max() / (np.median(ela) + 1e-3))
    verdict = "Signs of copy-move editing" if groups else "No copy-move found"
    banner(out, [verdict])
    ctx.add_image(out, "Copy-move matches (green = source, red = copy)")
    ctx.add_image(heatmap_overlay(img, ela, 0.6), "Error level analysis (bright = recompressed differently)")
    ctx.stat("Verdict", verdict, "bad" if groups else "good")
    ctx.stat("Copy-move regions", len(groups))
    ctx.stat("ELA contrast", round(ela_ratio, 1), "warn" if ela_ratio > 25 else None)
    if rows:
        ctx.table("Duplicated regions", ["#", "Matched points", "Shift (px)", "Source area"], rows, "copy_move.csv")
    ctx.note("Forensic cues, not proof. Repeated textures (tiles, windows) can trigger copy-move matches, and ELA varies with editing history. "
             "A trained model (e.g. on CASIA or IMD2020) and expert review are needed for conclusions.")


# ------------------------------------------------------------------ multi-view reconstruction

def _write_ply(points: np.ndarray, colors: np.ndarray) -> bytes:
    buf = io.StringIO()
    buf.write(f"ply\nformat ascii 1.0\nelement vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    for (x, y, z), (b, g, r) in zip(points, colors):
        buf.write(f"{x:.4f} {y:.4f} {z:.4f} {int(r)} {int(g)} {int(b)}\n")
    return buf.getvalue().encode()


@pipeline("reconstruction_3d", "3D reconstruction from photos",
          "Builds a sparse colored 3D point cloud from 2–8 overlapping photos (structure from motion) and exports a PLY file.",
          [Slot("images", "Photos in order, 60–80% overlap", "images", 2, 8)],
          [Param("focal", "Focal length (× image width)", "number", 1.2, 0.5, 3, 0.05, help="Most phone cameras: 0.8–1.2."),
           Param("max_error", "Max reprojection error (px)", "number", 3.0, 0.5, 10, 0.5)])
def reconstruction_3d(ctx):
    imgs = [fit(im, 1400) for _, im in ctx.images("images")]
    if len(imgs) < 2:
        raise UserError("Add at least two overlapping photos.")
    h, w = imgs[0].shape[:2]
    imgs = [cv2.resize(im, (w, h)) for im in imgs]
    sift = cv2.SIFT_create(8000)
    feats = [sift.detectAndCompute(to_gray(im), None) for im in imgs]
    flann = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})

    def match(i, j):
        ms = flann.knnMatch(feats[i][1], feats[j][1], k=2)
        good = [m for m, n in (x for x in ms if len(x) == 2) if m.distance < 0.75 * n.distance]
        return good

    good = match(0, 1)
    if len(good) < 30:
        raise UserError("The first two photos don't overlap enough. Take photos closer together, of a textured object.")
    p0 = np.float64([feats[0][0][m.queryIdx].pt for m in good])
    p1 = np.float64([feats[1][0][m.trainIdx].pt for m in good])
    # the focal length is rarely known: try the given value and common alternatives, keep the best-supported one
    best = None
    for fac in sorted({float(ctx.p("focal", 1.2)), 0.6, 0.75, 0.9, 1.05, 1.2, 1.5, 2.0}):
        Kc = np.array([[fac * w, 0, w / 2], [0, fac * w, h / 2], [0, 0, 1]], np.float64)
        E, inl = cv2.findEssentialMat(p0, p1, Kc, cv2.RANSAC, 0.999, 1.5)
        if E is None or E.shape != (3, 3):
            continue
        n_in, R_, t_, m_ = cv2.recoverPose(E, p0, p1, Kc, mask=inl)
        if best is None or n_in > best[0]:
            best = (n_in, fac, Kc, R_, t_, m_)
    if best is None or best[0] < 15:
        raise UserError("Couldn't estimate camera motion between the first two photos.")
    _, fac, K, R, t, inl2 = best
    f = fac * w
    poses = [(np.eye(3), np.zeros((3, 1))), (R, t)]
    P = [K @ np.hstack(poses[0]), K @ np.hstack(poses[1])]
    mask = inl2.ravel() > 0
    X = cv2.triangulatePoints(P[0], P[1], p0[mask].T, p1[mask].T)
    X = (X[:3] / X[3]).T
    # track which 3D point each keypoint of image 1 created (for adding more views)
    kp_to_3d = {good[k].trainIdx: idx for idx, k in enumerate(np.where(mask)[0])}
    cols = [imgs[0][int(y), int(x)] for x, y in p0[mask]]
    all_pts, all_cols = [X], [np.array(cols)]
    prev_kp_to_3d, prev_X = kp_to_3d, X
    for j in range(2, len(imgs)):
        gm = match(j - 1, j)
        obj, img_pts = [], []
        for m in gm:
            if m.queryIdx in prev_kp_to_3d:
                obj.append(prev_X[prev_kp_to_3d[m.queryIdx]])
                img_pts.append(feats[j][0][m.trainIdx].pt)
        if len(obj) < 12:
            ctx.note(f"Photo {j + 1} couldn't be placed (too little overlap with photo {j}); it was skipped.")
            break
        ok, rvec, tvec, inl_p = cv2.solvePnPRansac(np.float64(obj), np.float64(img_pts), K, None, reprojectionError=4.0)
        if not ok:
            break
        Rj, _ = cv2.Rodrigues(rvec)
        poses.append((Rj, tvec))
        Pj = K @ np.hstack((Rj, tvec))
        Pi = K @ np.hstack(poses[j - 1])
        a = np.float64([feats[j - 1][0][m.queryIdx].pt for m in gm])
        b = np.float64([feats[j][0][m.trainIdx].pt for m in gm])
        Xn = cv2.triangulatePoints(Pi, Pj, a.T, b.T)
        Xn = (Xn[:3] / Xn[3]).T
        all_pts.append(Xn)
        all_cols.append(np.array([imgs[j - 1][min(h - 1, int(y)), min(w - 1, int(x))] for x, y in a]))
        prev_kp_to_3d = {m.trainIdx: k for k, m in enumerate(gm)}
        prev_X = Xn
        P.append(Pj)
    pts = np.vstack(all_pts)
    cols = np.vstack(all_cols)
    # drop points behind the first camera or wildly far away
    keep = (pts[:, 2] > 0) & np.isfinite(pts).all(1)
    med = np.median(np.linalg.norm(pts[keep], axis=1)) if keep.any() else 1
    keep &= np.linalg.norm(pts, axis=1) < 6 * med
    pts, cols = pts[keep], cols[keep]
    if len(pts) < 20:
        raise UserError("Too few 3D points survived. Use more photos with steady overlap and a textured subject.")
    ctx.add_file(_write_ply(pts, cols), "point_cloud.ply")
    # preview: render the cloud from an oblique viewpoint
    c = pts.mean(0)
    view = np.zeros((h, w, 3), np.uint8)
    view[:] = (32, 28, 24)
    ang = math.radians(35)
    Ry = np.array([[math.cos(ang), 0, math.sin(ang)], [0, 1, 0], [-math.sin(ang), 0, math.cos(ang)]])
    q = (pts - c) @ Ry.T
    q[:, 2] += np.ptp(pts[:, 2]) * 1.6 + 1e-3
    uv = q[:, :2] / q[:, 2:3]
    lo, hi = np.percentile(uv, 2, axis=0), np.percentile(uv, 98, axis=0)
    sc = 0.85 * min(w / max(hi[0] - lo[0], 1e-6), h / max(hi[1] - lo[1], 1e-6))
    uv = (uv - (lo + hi) / 2) * sc + [w / 2, h / 2]
    for (u, v), col, z in sorted(zip(uv, cols, q[:, 2]), key=lambda t: -t[2]):
        if 0 <= u < w and 0 <= v < h:
            cv2.circle(view, (int(u), int(v)), 3, tuple(int(x) for x in col), -1)
    ctx.add_image(view, "Point cloud (rotated 35°)")
    ctx.stat("3D points", len(pts), "good")
    ctx.stat("Cameras placed", len(poses))
    ctx.stat("Photos used", f"{len(poses)}/{len(imgs)}")
    ctx.stat("Focal length used", round(fac, 2), unit="× width")
    sub = np.random.default_rng(0).choice(len(pts), min(4000, len(pts)), replace=False)
    ctx.result["points3d"] = {"xyz": (pts[sub] - c).round(4).tolist(), "rgb": cols[sub][:, ::-1].astype(int).tolist()}
    ctx.note("Sparse structure-from-motion with an estimated focal length; scale is arbitrary. For dense meshes, run COLMAP or a "
             "Gaussian-splatting pipeline on the same photos. Open point_cloud.ply in MeshLab or CloudCompare.")


# ------------------------------------------------------------------ palmprint

def palm_lines(img):
    g = cv2.createCLAHE(3.0, (8, 8)).apply(cv2.resize(to_gray(img), (400, int(400 * img.shape[0] / img.shape[1]))))
    resp = np.zeros(g.shape, np.float32)
    for th in np.arange(0, np.pi, np.pi / 8):
        k = cv2.getGaborKernel((21, 21), 4.0, th, 10.0, 0.5, 0, ktype=cv2.CV_32F)
        k -= k.mean()
        resp = np.maximum(resp, cv2.filter2D(255 - g.astype(np.float32), cv2.CV_32F, k))
    resp = cv2.normalize(resp, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return g, resp


@pipeline("palm_match", "Palmprint matching",
          "Enhances palm lines with Gabor filters and compares two palm photos by matching line features.",
          [Slot("a", "Palm photo A"), Slot("b", "Palm photo B")],
          [Param("threshold", "Match if score above", "number", 0.18, 0.02, 0.8, 0.01)])
def palm_match(ctx):
    a, b = ctx.image("a"), ctx.image("b")
    ga, la = palm_lines(a)
    gb, lb = palm_lines(b)
    orb = cv2.ORB_create(3000)
    ka, da = orb.detectAndCompute(la, None)
    kb, db = orb.detectAndCompute(lb, None)
    if da is None or db is None:
        raise UserError("Not enough palm detail. Use a sharp, well-lit photo of the open palm.")
    ms = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for m, n in (x for x in ms if len(x) == 2) if m.distance < 0.8 * n.distance]
    inliers = 0
    vis = cv2.hconcat([cv2.cvtColor(la, cv2.COLOR_GRAY2BGR), cv2.cvtColor(cv2.resize(lb, (lb.shape[1], la.shape[0])), cv2.COLOR_GRAY2BGR)])
    if len(good) >= 8:
        src = np.float32([ka[m.queryIdx].pt for m in good])
        dst = np.float32([kb[m.trainIdx].pt for m in good])
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if mask is not None:
            inliers = int(mask.sum())
            vis = cv2.drawMatches(cv2.cvtColor(la, cv2.COLOR_GRAY2BGR), ka, cv2.cvtColor(lb, cv2.COLOR_GRAY2BGR), kb,
                                  [m for m, k in zip(good, mask.ravel()) if k][:80], None, matchColor=(10, 151, 229), flags=2)
    score = inliers / max(1, min(len(ka), len(kb)))
    same = score >= float(ctx.p("threshold", 0.18))
    ctx.add_image(vis, "Line maps and matched features")
    ctx.stat("Result", "Likely same palm" if same else "Likely different palms", "good" if same else "bad")
    ctx.stat("Score", round(score, 3))
    ctx.stat("Consistent matches", inliers)
    ctx.note("A classical baseline for research with consenting volunteers. Deep palmprint models (trained on e.g. Tongji or PolyU) are far more accurate.")
