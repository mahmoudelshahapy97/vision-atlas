"""Helpers shared by several pipelines."""
from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

from ..core import (AMBER, GREEN, RED, Ctx, banner, box, color_for, draw_poly, finish_video, frames, is_video,
                    overlay_mask, point_in_poly, polygons_param, video_info, video_output)


def filter_classes(dets: list[dict], names: list[str] | None) -> list[dict]:
    if not names:
        return dets
    wanted = {n.lower() for n in names}
    return [d for d in dets if d["cls"].lower() in wanted]


def draw_dets(img: np.ndarray, dets: list[dict], masks: list[np.ndarray] | None = None, show_conf: bool = True,
              color_fn: Callable[[dict], tuple] | None = None, text_fn: Callable[[dict], str] | None = None) -> np.ndarray:
    out = img.copy()
    if masks:
        for d in dets:
            if d["i"] < len(masks):
                overlay_mask(out, masks[d["i"]], (color_fn or (lambda d: color_for(d["cls"])))(d))
    for d in dets:
        c = (color_fn or (lambda d: color_for(d["cls"])))(d)
        if text_fn:
            t = text_fn(d)
        else:
            t = d["cls"] + (f" #{d['id']}" if d.get("id") is not None else "") + (f" {d['conf']:.2f}" if show_conf else "")
        box(out, d["box"], t, c)
    return out


def run_media(ctx: Ctx, frame_fn: Callable[[np.ndarray, float, dict], np.ndarray], slot: str | None = None,
              caption: str = "Result", state: dict | None = None) -> dict:
    """Run frame_fn on an image, or on every Nth frame of a video, and save the annotated output.

    frame_fn(img, t_seconds, state) returns the annotated frame. state carries totals between frames;
    state["video"] tells the function whether it is processing a video.
    """
    f = ctx.file(slot)
    st = state if state is not None else {}
    if not is_video(f):
        st["video"] = False
        out = frame_fn(f.read(), 0.0, st)
        ctx.add_image(out, caption)
        return st
    st["video"] = True
    info = video_info(f.path)
    stride = int(ctx.p("stride", 1))
    st["fps"] = info.fps / stride
    writer = video_output(ctx, info.fps / stride)
    total = max(1, min(info.frames or 1, int(info.fps * 60)))
    n = 0
    for i, t, frame in frames(f.path, stride):
        out = frame_fn(frame, t, st)
        writer.write(out)
        if n == 0:
            st["first_frame"] = out
        n += 1
        ctx.progress(i / total)
    finish_video(ctx, writer, caption)
    st["frames"] = n
    if "first_frame" in st:
        ctx.add_image(st.pop("first_frame"), "First processed frame")
    ctx.stat("Frames analyzed", n)
    return st


def mask_area_pct(mask: np.ndarray) -> float:
    return float(mask.sum()) / mask.size * 100


def dominant_color(img: np.ndarray, mask: np.ndarray | None = None) -> tuple[str, tuple[int, int, int]]:
    """Name of the most common color in the region (k-means on HSV)."""
    px = img[mask.astype(bool)] if mask is not None and mask.any() else img.reshape(-1, 3)
    if len(px) == 0:
        return "unknown", (0, 0, 0)
    hsv = cv2.cvtColor(px.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    colorful = (hsv[:, 1] > 70) & (hsv[:, 2] > 60)
    if colorful.mean() > 0.2:   # ignore windows, shadows and highlights when the object has a clear color
        px = px[colorful]
    if len(px) > 4000:
        px = px[np.random.default_rng(0).choice(len(px), 4000, replace=False)]
    data = px.astype(np.float32)
    k = min(3, len(data))
    _, labels, centers = cv2.kmeans(data, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1), 3,
                                    cv2.KMEANS_PP_CENTERS)
    c = centers[np.bincount(labels.ravel()).argmax()].astype(int)
    return color_name(tuple(int(v) for v in c)), tuple(int(v) for v in c)


def color_name(bgr: tuple[int, int, int]) -> str:
    hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
    h, s, v = int(hsv[0]) * 2, int(hsv[1]), int(hsv[2])
    if v < 50:
        return "black"
    if s < 40:
        return "white" if v > 200 else "gray"
    if v < 110 and 10 <= h < 45:
        return "brown"
    for limit, name in ((15, "red"), (40, "orange"), (70, "yellow"), (160, "green"), (200, "cyan"),
                        (255, "blue"), (290, "purple"), (335, "pink"), (361, "red")):
        if h < limit:
            return name
    return "red"


def heatmap_overlay(img: np.ndarray, values: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    v = values.astype(np.float32)
    v = (v - v.min()) / (np.ptp(v) + 1e-6)
    hm = cv2.applyColorMap((v * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    if hm.shape[:2] != img.shape[:2]:
        hm = cv2.resize(hm, (img.shape[1], img.shape[0]))
    return cv2.addWeighted(img, 1 - alpha, hm, alpha, 0)


def to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def prompts_list(value: str | list | None) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in (value or "").replace("\n", ",").split(",") if p.strip()]


class ZoneMonitor:
    """Restricted-zone logic for one frame at a time, shared by the
    restricted_zone lab pipeline and its live camera analyzer.

    step() takes the detections of one frame (tracked, so ids persist) and
    returns the annotated frame, how many are inside, and the tracks that
    entered on this frame. A track counts as inside when its feet (the bottom
    centre of its box) are inside the polygon.
    """

    def __init__(self, zone_param, watch: set[str]):
        self.zone_param = zone_param
        self.watch = watch
        self.inside_ids: set[int] = set()
        self.dwell: dict[int, float] = {}

    def zone(self, img: np.ndarray) -> np.ndarray | None:
        h, w = img.shape[:2]
        zones = polygons_param(self.zone_param, w, h)
        return zones[0] if zones else None

    def step(self, img: np.ndarray, dets: list[dict], dt: float) -> tuple[np.ndarray, int, list[dict]]:
        zone = self.zone(img)
        out = img.copy()
        inside, entered, now_inside = 0, [], set()
        for d in dets:
            if d["cls"] not in self.watch:
                continue
            foot = ((d["box"][0] + d["box"][2]) / 2, d["box"][3])
            hit = zone is not None and point_in_poly(foot, zone)
            inside += hit
            if hit and d["id"] is not None:
                now_inside.add(d["id"])
                if d["id"] not in self.dwell:
                    entered.append(d)
                self.dwell[d["id"]] = self.dwell.get(d["id"], 0) + dt
            box(out, d["box"], ("VIOLATION " if hit else "") + d["cls"] + (f" #{d['id']}" if d["id"] is not None else ""),
                RED if hit else GREEN)
        self.inside_ids = now_inside
        if zone is not None:
            draw_poly(out, zone, RED if inside else AMBER, 0.2)
        banner(out, [f"In zone: {inside}"], (40, 40, 160) if inside else (30, 30, 30))
        return out, inside, entered
