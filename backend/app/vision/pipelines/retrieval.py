"""Search and dataset tools, plus scene understanding: similar images, text search, duplicates, dataset explorer,
auto-labeling with synthetic copy-paste, geolocation clues, visual Q&A, visual assistant."""
from __future__ import annotations

import io
import math
import random
import re
import zipfile
from collections import Counter

import cv2
import numpy as np

from ..core import (AMBER, COCO, GREEN, IMAGE, RED, WHITE, Param, Slot, UserError, banner, box, boxes_of, center,
                    color_for, fit, label, masks_of, pipeline)
from ..registry import manager
from .common import dominant_color, draw_dets, prompts_list, to_gray


# ------------------------------------------------------------------ shared helpers

def embed(ctx, imgs: list[np.ndarray]) -> np.ndarray:
    """YOLO26-cls feature vectors, mean-centered across the set so cosine similarity spreads out."""
    out = []
    with manager.use("yolo26-classify") as m:
        for i in range(0, len(imgs), 16):
            out += [e.cpu().numpy().ravel() for e in m.embed([fit(x, 640) for x in imgs[i:i + 16]], verbose=False)]
    E = np.stack(out).astype(np.float32)
    E -= E.mean(axis=0, keepdims=True) if len(E) > 2 else 0
    return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-8)


def color_hist(img: np.ndarray) -> np.ndarray:
    h = cv2.calcHist([cv2.cvtColor(fit(img, 256), cv2.COLOR_BGR2HSV)], [0, 1], None, [18, 8], [0, 180, 0, 256])
    return cv2.normalize(h, None).ravel()


def phash(img: np.ndarray) -> int:
    g = cv2.resize(to_gray(img), (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(g)[:8, :8]
    bits = (d > np.median(d[1:].ravel())).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def contact_sheet(items: list[tuple[np.ndarray, str]], cols: int = 4, cell: int = 260) -> np.ndarray:
    rows = math.ceil(len(items) / cols)
    sheet = np.full((rows * (cell + 34), cols * cell, 3), 255, np.uint8)
    for k, (img, cap) in enumerate(items):
        r, c = divmod(k, cols)
        t = fit(img, cell - 8)
        y0, x0 = r * (cell + 34) + 4 + (cell - 8 - t.shape[0]) // 2, c * cell + 4 + (cell - 8 - t.shape[1]) // 2
        sheet[y0:y0 + t.shape[0], x0:x0 + t.shape[1]] = t
        cv2.putText(sheet, cap[:30], (c * cell + 6, r * (cell + 34) + cell + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1, cv2.LINE_AA)
    return sheet


def gallery(ctx, slot: str = "images", minimum: int = 2) -> list[tuple[str, np.ndarray]]:
    g = ctx.images(slot)
    if len(g) < minimum:
        raise UserError(f"Add at least {minimum} images.")
    return g


# ------------------------------------------------------------------ similar image search

@pipeline("similar_search", "Visual similarity search",
          "Ranks a catalog of images by visual similarity to a query photo (YOLO26 embeddings + color).",
          [Slot("query", "Query image"), Slot("gallery", "Catalog images", "images", 2, 200)],
          [Param("color_weight", "Color importance", "number", 0.25, 0, 1, 0.05),
           Param("top", "Results to show", "int", 8, 1, 24)], models=["yolo26-classify"])
def similar_search(ctx):
    q = ctx.image("query")
    gal = gallery(ctx, "gallery")
    E = embed(ctx, [q] + [g for _, g in gal])
    sims = E[1:] @ E[0]
    hq = color_hist(q)
    hs = np.array([cv2.compareHist(hq, color_hist(g), cv2.HISTCMP_CORREL) for _, g in gal])
    w = float(ctx.p("color_weight", 0.25))
    score = (1 - w) * sims + w * hs
    order = np.argsort(-score)
    top = int(ctx.p("top", 8))
    ctx.add_image(contact_sheet([(q, "QUERY")] + [(gal[i][1], f"{k + 1}. {gal[i][0]} {score[i]:.2f}") for k, i in enumerate(order[:top])]), "Most similar")
    ctx.stat("Catalog size", len(gal))
    ctx.stat("Best match", gal[order[0]][0])
    ctx.stat("Best score", round(float(score[order[0]]), 3))
    ctx.table("Ranking", ["Rank", "Image", "Score", "Shape/content", "Color"],
              [[k + 1, gal[i][0], round(float(score[i]), 3), round(float(sims[i]), 3), round(float(hs[i]), 3)] for k, i in enumerate(order)], "ranking.csv")
    ctx.note("For large catalogs, store these embeddings in a vector database (FAISS, pgvector) instead of recomputing them.")


# ------------------------------------------------------------------ text to image search

@pipeline("text_image_search", "Text-to-image search",
          "Finds the images in a collection that best match a description, using YOLOE-26 open-vocabulary detection.",
          [Slot("images", "Image collection", "images", 2, 200)],
          [Param("query", "Search for", "text", "person with a backpack", help="Comma-separate several things that must all appear."),
           Param("top", "Results to show", "int", 8, 1, 24)], models=["yoloe26"])
def text_image_search(ctx):
    gal = gallery(ctx)
    terms = prompts_list(ctx.p("query"))
    if not terms:
        raise UserError("Type what you're looking for.")
    scored = []
    for n, (name, img) in enumerate(gal):
        r = ctx.yoloe(terms, img, conf=0.05)[0]
        dets = boxes_of(r)
        best = {t: max([d["conf"] for d in dets if d["cls"] == t], default=0.0) for t in terms}
        s = float(np.mean(list(best.values()))) if all(best.values()) else float(np.mean(list(best.values()))) * 0.4
        scored.append((s, name, img, [d for d in dets if d["conf"] > 0.15]))
        ctx.progress((n + 1) / len(gal))
    scored.sort(key=lambda x: -x[0])
    top = int(ctx.p("top", 8))
    ctx.add_image(contact_sheet([(draw_dets(img, dets), f"{k + 1}. {name} {s:.2f}") for k, (s, name, img, dets) in enumerate(scored[:top])]), "Best matches")
    ctx.stat("Images searched", len(gal))
    ctx.stat("Matches (score > 0.25)", sum(s > 0.25 for s, *_ in scored), "good")
    ctx.stat("Best match", scored[0][1])
    ctx.table("Results", ["Rank", "Image", "Score", "Objects found"],
              [[k + 1, name, round(s, 3), ", ".join(sorted({d["cls"] for d in dets}))] for k, (s, name, _, dets) in enumerate(scored)], "search.csv")
    ctx.note("YOLOE matches things you can point at. Whole-scene queries ('a sunny beach') work better with a CLIP model and a vector database.")


# ------------------------------------------------------------------ duplicates

@pipeline("duplicate_finder", "Duplicate and near-duplicate finder",
          "Groups identical and near-identical images (resized, recompressed, cropped, brightened) using perceptual hashes and embeddings.",
          [Slot("images", "Images", "images", 2, 300)],
          [Param("hash_distance", "Max hash difference (bits)", "int", 10, 0, 24),
           Param("similarity", "Min embedding similarity", "number", 0.9, 0.5, 1.0, 0.01)], models=["yolo26-classify"])
def duplicate_finder(ctx):
    gal = gallery(ctx)
    names = [n for n, _ in gal]
    hashes = [phash(g) for _, g in gal]
    E = embed(ctx, [g for _, g in gal])
    S = E @ E.T
    parent = list(range(len(gal)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    pairs = []
    for i in range(len(gal)):
        for j in range(i + 1, len(gal)):
            hd = hamming(hashes[i], hashes[j])
            if hd <= int(ctx.p("hash_distance", 10)) or S[i, j] >= float(ctx.p("similarity", 0.9)):
                parent[find(i)] = find(j)
                pairs.append([names[i], names[j], hd, round(float(S[i, j]), 3), "exact" if hd <= 2 else "near-duplicate"])
    groups: dict[int, list[int]] = {}
    for i in range(len(gal)):
        groups.setdefault(find(i), []).append(i)
    dup = [g for g in groups.values() if len(g) > 1]
    for k, g in enumerate(dup[:6]):
        ctx.add_image(contact_sheet([(gal[i][1], names[i]) for i in g[:8]], cols=min(4, len(g))), f"Group {k + 1}")
    ctx.stat("Images", len(gal))
    ctx.stat("Duplicate groups", len(dup), "warn" if dup else "good")
    ctx.stat("Redundant images", sum(len(g) - 1 for g in dup))
    if pairs:
        ctx.table("Matching pairs", ["Image A", "Image B", "Hash difference", "Embedding similarity", "Type"], pairs, "duplicates.csv")
    ctx.table("Groups", ["Group", "Images", "Keep", "Remove"],
              [[k + 1, len(g), names[g[0]], ", ".join(names[i] for i in g[1:])] for k, g in enumerate(dup)])


# ------------------------------------------------------------------ dataset explorer

@pipeline("dataset_explorer", "Image dataset explorer",
          "Clusters a dataset by visual content, maps it in 2D, and flags outliers, duplicates, and dark, blurry or tiny images.",
          [Slot("images", "Dataset images", "images", 3, 300)],
          [Param("clusters", "Clusters (0 = automatic)", "int", 0, 0, 20), Param("detect", "Count objects with YOLO26", "bool", True)],
          models=["yolo26-classify", "yolo26-detect"])
def dataset_explorer(ctx):
    gal = gallery(ctx, minimum=3)
    names = [n for n, _ in gal]
    E = embed(ctx, [g for _, g in gal])
    n = len(gal)
    k = int(ctx.p("clusters", 0)) or max(2, min(10, round(math.sqrt(n / 2))))
    k = min(k, n)
    _, labels, centers = cv2.kmeans(E, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4), 5, cv2.KMEANS_PP_CENTERS)
    labels = labels.ravel()
    dist = np.linalg.norm(E - centers[labels], axis=1)
    z = (dist - dist.mean()) / (dist.std() + 1e-6)
    Xc = E - E.mean(0)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    P = Xc @ Vt[:2].T
    hashes = [phash(g) for _, g in gal]
    rows, cls_counter = [], Counter()
    for i, (name, img) in enumerate(gal):
        g = to_gray(img)
        issues = []
        if g.mean() < 40:
            issues.append("dark")
        if g.mean() > 225:
            issues.append("overexposed")
        if cv2.Laplacian(g, cv2.CV_64F).var() < 60:
            issues.append("blurry")
        if min(img.shape[:2]) < 224:
            issues.append("small")
        if any(hamming(hashes[i], hashes[j]) <= 6 for j in range(i)):
            issues.append("duplicate")
        if z[i] > 2.0:
            issues.append("outlier")
        objs = ""
        if ctx.p("detect", True):
            dets = boxes_of(ctx.predict("yolo26-detect", img, conf=0.35)[0])
            c = Counter(d["cls"] for d in dets)
            cls_counter.update(c)
            objs = ", ".join(f"{a}×{b}" for a, b in c.most_common(4))
        rows.append([name, int(labels[i]) + 1, f"{img.shape[1]}×{img.shape[0]}", round(float(z[i]), 2), ", ".join(issues), objs])
        ctx.progress((i + 1) / n)
    ctx.result["chart"] = {"type": "scatter", "title": "Dataset map (similar images sit together)",
                           "series": [{"name": f"Cluster {c + 1}", "points": [[round(float(P[i, 0]), 4), round(float(P[i, 1]), 4), names[i]]
                                                                             for i in range(n) if labels[i] == c]} for c in range(k)],
                           "x_label": "Component 1", "y_label": "Component 2"}
    for c in range(min(k, 6)):
        members = [i for i in range(n) if labels[i] == c][:8]
        ctx.add_image(contact_sheet([(gal[i][1], names[i]) for i in members], cols=4, cell=200), f"Cluster {c + 1} ({sum(labels == c)} images)")
    ctx.stat("Images", n)
    ctx.stat("Clusters", k)
    ctx.stat("Outliers", sum("outlier" in r[4] for r in rows), "warn")
    ctx.stat("Duplicates", sum("duplicate" in r[4] for r in rows), "warn")
    ctx.stat("Quality issues", sum(bool(r[4]) for r in rows))
    ctx.table("Images", ["Image", "Cluster", "Size", "Outlier score", "Issues", "Objects"], rows, "dataset_report.csv")
    if cls_counter:
        top = cls_counter.most_common(12)
        ctx.table("Object classes", ["Class", "Instances"], [list(t) for t in top])


# ------------------------------------------------------------------ dataset builder (auto-label + synthesis)

def _aug(img, boxes, rng):
    h, w = img.shape[:2]
    out, bx = img.copy(), [list(b) for b in boxes]
    if rng.random() < 0.5:
        out = cv2.flip(out, 1)
        bx = [[c, w - x2, y1, w - x1, y2] for c, x1, y1, x2, y2 in bx]
    a, b = rng.uniform(0.75, 1.25), rng.uniform(-25, 25)
    out = cv2.convertScaleAbs(out, alpha=a, beta=b)
    ang = rng.uniform(-8, 8)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    out = cv2.warpAffine(out, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    nb = []
    for c, x1, y1, x2, y2 in bx:
        pts = np.array([[x1, y1, 1], [x2, y1, 1], [x2, y2, 1], [x1, y2, 1]], np.float32) @ M.T
        nx1, ny1 = np.clip(pts.min(0), 0, [w, h])
        nx2, ny2 = np.clip(pts.max(0), 0, [w, h])
        if (nx2 - nx1) > 4 and (ny2 - ny1) > 4:
            nb.append([c, nx1, ny1, nx2, ny2])
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (5, 5), 0)
    if rng.random() < 0.3:
        out = np.clip(out.astype(np.int16) + rng.normal(0, 8, out.shape).astype(np.int16), 0, 255).astype(np.uint8)
    return out, nb


@pipeline("dataset_builder", "Auto-label and synthetic dataset builder",
          "Labels your images automatically with YOLO26 or YOLOE-26, creates augmented and copy-paste synthetic images, "
          "and packages a ready-to-train YOLO dataset (ZIP with data.yaml).",
          [Slot("images", "Images", "images", 1, 200)],
          [Param("source", "Labeler", "select", "YOLOE-26 prompts", options=["YOLOE-26 prompts", "YOLO26 COCO classes"]),
           Param("prompts", "Classes (YOLOE prompts)", "text", "person, bus, car"),
           Param("classes", "Classes (COCO)", "multiselect", ["person", "car"], options=COCO),
           Param("augment", "Augmented copies per image", "int", 2, 0, 10),
           Param("paste", "Copy-paste synthetic images", "int", 4, 0, 100, help="Cut labeled objects out and paste them onto other images."),
           Param("val_split", "Validation share", "number", 0.2, 0, 0.5, 0.05),
           Param("conf", "Label confidence", "number", 0.3, 0.05, 0.95, 0.05)],
          models=["yoloe26", "yolo26-segment"])
def dataset_builder(ctx):
    gal = gallery(ctx, minimum=1)
    use_yoloe = ctx.p("source", "YOLOE-26 prompts").startswith("YOLOE")
    names = prompts_list(ctx.p("prompts")) if use_yoloe else list(ctx.p("classes", []) or ["person"])
    if not names:
        raise UserError("List the classes to label.")
    cid = {n: i for i, n in enumerate(names)}
    rng = np.random.default_rng(0)
    conf = float(ctx.p("conf", 0.3))
    samples, cutouts = [], []
    for k, (name, img) in enumerate(gal):
        img = fit(img, 1280)
        if use_yoloe:
            r = ctx.yoloe(names, img, conf=conf)[0]
        else:
            r = ctx.predict("yolo26-segment", img, conf=conf)[0]
        dets = [d for d in boxes_of(r) if d["cls"] in cid]
        masks = masks_of(r, img.shape)
        boxes = [[cid[d["cls"]], *d["box"]] for d in dets]
        samples.append((name.rsplit(".", 1)[0], img, boxes))
        for d in dets:
            if d["i"] < len(masks) and masks[d["i"]].sum() > 400:
                x1, y1, x2, y2 = map(int, d["box"])
                cutouts.append((cid[d["cls"]], img[y1:y2, x1:x2].copy(), masks[d["i"]][y1:y2, x1:x2].copy()))
        ctx.progress(0.5 * (k + 1) / len(gal))
    out_samples = list(samples)
    for name, img, boxes in samples:
        for a in range(int(ctx.p("augment", 2))):
            ai, ab = _aug(img, boxes, rng)
            out_samples.append((f"{name}_aug{a + 1}", ai, ab))
    n_paste = int(ctx.p("paste", 4)) if cutouts else 0
    for p in range(n_paste):
        bname, bg, bboxes = samples[int(rng.integers(len(samples)))]
        canvas, nb = bg.copy(), [list(b) for b in bboxes]
        for _ in range(int(rng.integers(1, 4))):
            c, patch, m = cutouts[int(rng.integers(len(cutouts)))]
            s = float(rng.uniform(0.5, 1.1))
            ph, pw = max(8, int(patch.shape[0] * s)), max(8, int(patch.shape[1] * s))
            if ph >= canvas.shape[0] or pw >= canvas.shape[1]:
                continue
            patch_r = cv2.resize(patch, (pw, ph))
            m_r = cv2.GaussianBlur(cv2.resize(m.astype(np.float32), (pw, ph)), (5, 5), 0)[..., None]
            y0, x0 = int(rng.integers(0, canvas.shape[0] - ph)), int(rng.integers(0, canvas.shape[1] - pw))
            roi = canvas[y0:y0 + ph, x0:x0 + pw]
            canvas[y0:y0 + ph, x0:x0 + pw] = (roi * (1 - m_r) + patch_r * m_r).astype(np.uint8)
            nb.append([c, x0, y0, x0 + pw, y0 + ph])
        out_samples.append((f"synthetic_{p + 1:03d}", canvas, nb))
    random.Random(0).shuffle(out_samples)
    n_val = int(round(len(out_samples) * float(ctx.p("val_split", 0.2))))
    buf = io.BytesIO()
    counts = Counter()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (name, img, boxes) in enumerate(out_samples):
            split = "val" if i < n_val else "train"
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            z.writestr(f"dataset/images/{split}/{name}.jpg", jpg.tobytes())
            h, w = img.shape[:2]
            lines = []
            for c, x1, y1, x2, y2 in boxes:
                lines.append(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
                counts[names[c]] += 1
            z.writestr(f"dataset/labels/{split}/{name}.txt", "\n".join(lines))
        yaml = "path: .\ntrain: images/train\nval: images/val\nnames:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(names))
        z.writestr("dataset/data.yaml", yaml)
        z.writestr("dataset/README.txt", "Train with:\n  yolo detect train data=data.yaml model=yolo26n.pt epochs=100 imgsz=640\n\n"
                   "Labels were generated automatically. Review them (e.g. in CVAT or Label Studio) before training.\n")
    ctx.add_file(buf.getvalue(), "yolo_dataset.zip")
    prev = []
    for name, img, boxes in out_samples[:8]:
        v = img.copy()
        for c, x1, y1, x2, y2 in boxes:
            box(v, [x1, y1, x2, y2], names[c], color_for(names[c]))
        prev.append((v, name))
    ctx.add_image(contact_sheet(prev), "Preview with labels")
    ctx.stat("Images in dataset", len(out_samples))
    ctx.stat("Train / val", f"{len(out_samples) - n_val} / {n_val}")
    ctx.stat("Labels", sum(counts.values()))
    ctx.stat("Synthetic images", n_paste)
    ctx.table("Labels per class", ["Class", "Boxes"], [[n, counts[n]] for n in names], "label_counts.csv")
    if not cutouts and int(ctx.p("paste", 4)):
        ctx.note("No objects with masks were found to cut out, so no copy-paste images were made.")


# ------------------------------------------------------------------ geolocation clues

SCENE_CLUES = {
    "mosque": ("Islamic architecture", ["Middle East & North Africa", "South Asia", "Southeast Asia"]),
    "minaret": ("Islamic architecture", ["Middle East & North Africa"]),
    "church": ("Church architecture", ["Europe", "Americas"]), "monastery": ("Monastery", ["Europe", "East Asia"]),
    "palace": ("Palace architecture", ["Europe", "Asia"]), "pagoda": ("Pagoda", ["East Asia", "Southeast Asia"]),
    "stupa": ("Stupa", ["South Asia", "Southeast Asia"]), "dome": ("Domed building", ["Middle East & North Africa", "Europe"]),
    "Arabian_camel": ("Camel", ["Middle East & North Africa"]), "alp": ("High mountains", ["Europe", "Asia", "Americas"]),
    "seashore": ("Coastline", []), "sandbar": ("Sandy coast", []), "volcano": ("Volcano", ["East Asia", "Americas", "Oceania"]),
    "trolleybus": ("Trolleybus", ["Europe"]), "streetcar": ("Tram", ["Europe"]), "cab": ("Taxi", []),
    "school_bus": ("Yellow school bus", ["North America"]), "police_van": ("Police van", []),
    "rickshaw": ("Rickshaw", ["South Asia", "Southeast Asia"]), "jinrikisha": ("Rickshaw", ["South Asia", "East Asia"]),
    "totem_pole": ("Totem pole", ["North America"]), "yurt": ("Yurt", ["Central Asia"]), "igloo": ("Igloo", ["Arctic"]),
}
LANG_WORDS = {
    "Spanish": ({"el", "la", "de", "los", "las", "y", "en", "calle", "cero", "emisiones", "salida", "entrada", "avenida"},
                ["Spain", "Latin America"]),
    "French": ({"le", "la", "les", "des", "et", "rue", "sortie", "entrée", "boulevard"}, ["France", "North & West Africa", "Canada"]),
    "German": ({"der", "die", "das", "und", "straße", "strasse", "ausgang", "eingang"}, ["Germany / Austria / Switzerland"]),
    "Italian": ({"il", "della", "via", "uscita", "ingresso"}, ["Italy"]),
    "Portuguese": ({"rua", "saída", "não", "avenida", "do", "da"}, ["Portugal", "Brazil"]),
    "English": ({"the", "street", "road", "exit", "stop", "and", "avenue"}, ["English-speaking countries"]),
}


@pipeline("geolocation_clues", "Image geolocation clues",
          "Suggests likely regions from visual and text clues: script and language of signs, architecture, vehicles and landscape.",
          IMAGE, [], models=["yolo26-classify", "yolo26-detect", "easyocr"])
def geolocation_clues(ctx):
    img = ctx.image()
    scores: Counter = Counter()
    evidence = []
    r = ctx.predict("yolo26-classify", img)[0]
    probs = r.probs.data.cpu().numpy()
    for i in np.argsort(-probs)[:10]:
        nm = r.names[int(i)]
        if nm in SCENE_CLUES and probs[i] > 0.02:
            what, regions = SCENE_CLUES[nm]
            for rg in regions:
                scores[rg] += float(probs[i]) * 3
            evidence.append(["Scene", f"{what} ({nm}, {probs[i]:.0%})", ", ".join(regions) or "—"])
    from .ocr import ocr_lines, is_arabic
    lines = ocr_lines(ctx.ocr(fit(img, 1600), ("ar", "en")))
    text = " ".join(l["text"] for l in lines)
    def real_arabic(l):
        letters = [ch for ch in l["text"] if ch.isalpha()]
        ar_share = sum(is_arabic(ch) for ch in letters) / max(1, len(letters))
        return l["conf"] > 0.6 and ar_share > 0.7 and len(letters) >= 4
    if text:
        ar_lines = [l for l in lines if real_arabic(l)]
        if ar_lines:
            scores["Middle East & North Africa"] += 2.0 * min(3, len(ar_lines))
            evidence.append(["Script", f"Arabic text: {ar_lines[0]['text'][:30]}", "Middle East & North Africa"])
        words = set(re.findall(r"[a-záéíóúñüßàèçãõ]+", text.lower()))
        if words:
            evidence.append(["Script", "Latin text", "—"])
        for lang, (vocab, regions) in LANG_WORDS.items():
            hits = words & vocab
            if hits:
                for rg in regions:
                    scores[rg] += 1.0 * len(hits)
                evidence.append(["Language", f"{lang} words: {', '.join(sorted(hits))}", ", ".join(regions)])
    dets = boxes_of(ctx.predict("yolo26-detect", img, conf=0.4)[0])
    c = Counter(d["cls"] for d in dets)
    if c:
        evidence.append(["Objects", ", ".join(f"{k}×{v}" for k, v in c.most_common(5)), "context"])
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = float(((hsv[..., 0] > 35) & (hsv[..., 0] < 85) & (hsv[..., 1] > 60)).mean())
    sandy = float(((hsv[..., 0] > 8) & (hsv[..., 0] < 25) & (hsv[..., 1] > 50) & (hsv[..., 2] > 140)).mean())
    if green > 0.35:
        evidence.append(["Landscape", f"Lush vegetation ({green:.0%} of image)", "temperate / tropical"])
    if sandy > 0.3:
        scores["Middle East & North Africa"] += 1
        evidence.append(["Landscape", f"Sand / arid tones ({sandy:.0%})", "arid regions"])
    ranked = scores.most_common(5)
    total = sum(v for _, v in ranked) or 1
    out = img.copy()
    banner(out, ["Likely: " + (ranked[0][0] if ranked else "not enough clues")])
    ctx.add_image(out, "Image")
    ctx.stat("Top guess", ranked[0][0] if ranked else "not enough clues", "good" if ranked else "warn")
    if ranked:
        ctx.table("Regions", ["Region", "Confidence"], [[rg, f"{v / total:.0%}"] for rg, v in ranked])
    ctx.table("Evidence", ["Type", "Clue", "Points to"], evidence)
    if text:
        ctx.text(text)
    ctx.note("Rule-based and approximate. Don't use it to locate private individuals. Learned geolocation (e.g. a CLIP model trained on geotagged photos) is far more precise.")


# ------------------------------------------------------------------ visual Q&A

def _where(b, w, h) -> str:
    cx, cy = center(b)
    hz = "on the left" if cx < w / 3 else "on the right" if cx > 2 * w / 3 else "in the center"
    vt = "at the top" if cy < h / 3 else "at the bottom" if cy > 2 * h / 3 else ""
    return f"{hz} {vt}".strip()


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    if word == "person":
        return "people"
    return word if word.endswith("s") else word + "s"


@pipeline("visual_qa", "Visual question answering",
          "Ask a question about an image: how many, is there, what color, where is, what does the text say, what is this person doing.",
          IMAGE, [Param("question", "Question", "text", "How many people are there?")],
          models=["yoloe26", "yolo26-detect", "yolo26-classify", "yolo26-pose", "easyocr"])
def visual_qa(ctx):
    img = ctx.image()
    h, w = img.shape[:2]
    q = str(ctx.p("question", "")).strip()
    ql = q.lower().rstrip("?").strip()
    out = img.copy()
    answer = None

    def find(thing):
        thing = re.sub(r"^(the|a|an|any|some)\s+", "", thing.strip())
        thing = {"people": "person", "persons": "person", "men": "man", "women": "woman", "cars": "car", "buses": "bus"}.get(thing, thing)
        if thing.endswith("s") and thing[:-1] in COCO:
            thing = thing[:-1]
        if thing in COCO:
            dets = [d for d in boxes_of(ctx.predict("yolo26-detect", img, conf=0.35)[0]) if d["cls"] == thing]
        else:
            dets = boxes_of(ctx.yoloe([thing], img, conf=0.2)[0])
        return thing, dets

    m = re.match(r"how many (.+?)( are there| do you see| can you see| in the (image|picture|photo)|$)", ql)
    if m:
        thing, dets = find(m.group(1))
        answer = f"I count {len(dets)} {_plural(thing, len(dets))}."
        out = draw_dets(img, dets)
    if answer is None:
        m = re.match(r"(is|are) there (a |an |any )?(.+?)( in the (image|picture|photo))?$", ql)
        if m:
            thing, dets = find(m.group(3))
            answer = f"Yes — {len(dets)} {_plural(thing, len(dets))}, {_where(dets[0]['box'], w, h)}." if dets else f"No, I don't see any {_plural(thing, 2)}."
            out = draw_dets(img, dets)
    if answer is None:
        m = re.match(r"what colou?r (is|are) (the )?(.+)$", ql)
        if m:
            thing, dets = find(m.group(3))
            if dets:
                d = max(dets, key=lambda d: (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]))
                x1, y1, x2, y2 = map(int, d["box"])
                name, _ = dominant_color(img[y1:y2, x1:x2])
                answer = f"The {thing} is mostly {name}."
                out = draw_dets(img, [d])
            else:
                answer = f"I can't find a {thing} in the image."
    if answer is None:
        m = re.match(r"where (is|are) (the )?(.+)$", ql)
        if m:
            thing, dets = find(m.group(3))
            answer = ("; ".join(f"one {_where(d['box'], w, h)}" for d in dets[:4]).capitalize() + ".") if dets else f"I can't find a {thing}."
            if dets:
                answer = f"{len(dets)} {_plural(thing, len(dets))}: " + answer[0].lower() + answer[1:]
            out = draw_dets(img, dets)
    if answer is None and re.search(r"(text|sign|written|say|read)", ql):
        from .ocr import ocr_lines
        lines = ocr_lines(ctx.ocr(fit(img, 1600), ("ar", "en")))
        txt = " / ".join(l["text"] for l in lines if l["conf"] > 0.3)
        answer = f"The text says: {txt}" if txt else "I can't find readable text."
    if answer is None and re.search(r"doing|activity|sitting|standing", ql):
        from .people import pose_predict, posture, draw_skeleton
        people = pose_predict(ctx, img, 0.3)
        acts = Counter(posture(p) for p in people)
        for p in people:
            draw_skeleton(out, p)
        answer = ("I see " + ", ".join(f"{v} {('person' if v == 1 else 'people')} {k}" for k, v in acts.items()) + ".") if people else "I don't see anyone."
    if answer is None:
        r = ctx.predict("yolo26-classify", img)[0]
        top = r.names[int(r.probs.top1)].replace("_", " ")
        dets = boxes_of(ctx.predict("yolo26-detect", img, conf=0.35)[0])
        c = Counter(d["cls"] for d in dets)
        objs = ", ".join(f"{v} {_plural(k, v)}" for k, v in c.most_common(5))
        answer = f"It looks like a scene with {top}" + (f"; I can see {objs}." if objs else ".")
        out = draw_dets(img, dets)
        ctx.note("I answer counting, presence, color, location, text and activity questions. Open-ended questions need a vision-language model such as Qwen2.5-VL.")
    ctx.add_image(out, "Evidence")
    ctx.text(f"Q: {q}\nA: {answer}")
    ctx.stat("Answer", answer)
    ctx.result["speak"] = answer


# ------------------------------------------------------------------ visual assistant

AR_NAMES = {"person": "شخص", "bicycle": "دراجة", "car": "سيارة", "motorcycle": "دراجة نارية", "airplane": "طائرة", "bus": "حافلة",
            "train": "قطار", "truck": "شاحنة", "boat": "قارب", "traffic light": "إشارة مرور", "fire hydrant": "صنبور إطفاء",
            "stop sign": "إشارة توقف", "parking meter": "عداد مواقف", "bench": "مقعد", "bird": "طائر", "cat": "قطة", "dog": "كلب",
            "horse": "حصان", "sheep": "خروف", "cow": "بقرة", "elephant": "فيل", "bear": "دب", "zebra": "حمار وحشي", "giraffe": "زرافة",
            "backpack": "حقيبة ظهر", "umbrella": "مظلة", "handbag": "حقيبة يد", "tie": "ربطة عنق", "suitcase": "حقيبة سفر",
            "frisbee": "صحن طائر", "skis": "زلاجات", "snowboard": "لوح تزلج", "sports ball": "كرة", "kite": "طائرة ورقية",
            "baseball bat": "مضرب بيسبول", "baseball glove": "قفاز بيسبول", "skateboard": "لوح تزلج", "surfboard": "لوح ركوب الأمواج",
            "tennis racket": "مضرب تنس", "bottle": "زجاجة", "wine glass": "كأس", "cup": "كوب", "fork": "شوكة", "knife": "سكين",
            "spoon": "ملعقة", "bowl": "وعاء", "banana": "موزة", "apple": "تفاحة", "sandwich": "شطيرة", "orange": "برتقالة",
            "broccoli": "بروكلي", "carrot": "جزرة", "hot dog": "نقانق", "pizza": "بيتزا", "donut": "دونات", "cake": "كعكة",
            "chair": "كرسي", "couch": "أريكة", "potted plant": "نبتة", "bed": "سرير", "dining table": "طاولة", "toilet": "مرحاض",
            "tv": "تلفاز", "laptop": "حاسوب محمول", "mouse": "فأرة", "remote": "جهاز تحكم", "keyboard": "لوحة مفاتيح",
            "cell phone": "هاتف", "microwave": "ميكروويف", "oven": "فرن", "toaster": "محمصة", "sink": "حوض", "refrigerator": "ثلاجة",
            "book": "كتاب", "clock": "ساعة", "vase": "مزهرية", "scissors": "مقص", "teddy bear": "دمية دب", "hair drier": "مجفف شعر",
            "toothbrush": "فرشاة أسنان"}
AR_PLURAL = {"person": "الأشخاص", "car": "السيارات", "bus": "الحافلات", "truck": "الشاحنات", "bicycle": "الدراجات",
             "motorcycle": "الدراجات النارية", "chair": "الكراسي", "bottle": "الزجاجات", "cup": "الأكواب", "book": "الكتب",
             "dog": "الكلاب", "cat": "القطط", "bird": "الطيور", "traffic light": "إشارات المرور", "backpack": "حقائب الظهر",
             "handbag": "حقائب اليد", "suitcase": "حقائب السفر", "bench": "المقاعد", "potted plant": "النباتات",
             "cell phone": "الهواتف", "laptop": "الحواسيب", "tv": "أجهزة التلفاز", "umbrella": "المظلات", "boat": "القوارب"}
AR_WHERE = {"on the left": "على اليسار", "on the right": "على اليمين", "in the center": "في المنتصف"}


@pipeline("visual_assistant", "Visual assistant for blind users",
          "Describes what's in front of the camera, warns about the nearest obstacle, and reads visible text — then speaks it aloud.",
          IMAGE, [Param("language", "Language", "select", "English", options=["English", "العربية"]),
                  Param("read_text", "Read text", "bool", True), Param("depth", "Warn about the nearest object", "bool", True)],
          models=["yolo26-detect", "easyocr", "midas"])
def visual_assistant(ctx):
    img = fit(ctx.image(), 1280)
    h, w = img.shape[:2]
    ar = ctx.p("language", "English") != "English"
    dets = boxes_of(ctx.predict("yolo26-detect", img, conf=0.4)[0])
    groups: dict[str, list] = {}
    for d in dets:
        groups.setdefault(d["cls"], []).append(d)
    parts = []
    for cls, ds in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:6]:
        where = Counter(_where(d["box"], w, h).split(" at ")[0] for d in ds).most_common(1)[0][0]
        if ar:
            one, many = AR_NAMES.get(cls, cls), AR_PLURAL.get(cls, AR_NAMES.get(cls, cls))
            phrase = one if len(ds) == 1 else f"اثنان من {many}" if len(ds) == 2 else f"{len(ds)} من {many}"
            parts.append(f"{phrase} {AR_WHERE.get(where, '')}")
        else:
            parts.append(f"{len(ds) if len(ds) > 1 else 'a'} {_plural(cls, len(ds))} {where}")
    if ar:
        speech = ("أرى " + "، و".join(parts) + ".") if parts else "لا أرى أشياء واضحة أمامك."
    else:
        speech = ("I see " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + ".") if parts else "I don't see any clear objects."
    out = draw_dets(img, dets)
    if ctx.p("depth", True) and dets:
        try:
            from .enhance import midas_depth
            dmap = midas_depth(img)
            dn = (dmap - dmap.min()) / (np.ptp(dmap) + 1e-6)
            near = max(dets, key=lambda d: float(np.median(dn[int(d["box"][1]):int(d["box"][3]), int(d["box"][0]):int(d["box"][2])])))
            closeness = float(np.median(dn[int(near["box"][1]):int(near["box"][3]), int(near["box"][0]):int(near["box"][2])]))
            if closeness > 0.6:
                where = _where(near["box"], w, h).split(" at ")[0]
                speech += (f" تنبيه: {AR_NAMES.get(near['cls'], near['cls'])} قريب {AR_WHERE.get(where, '')}." if ar
                           else f" Careful: a {near['cls']} is close, {where}.")
                box(out, near["box"], "NEAREST", RED)
        except Exception as e:  # depth is optional
            ctx.note(f"Depth warning skipped: {e}")
    if ctx.p("read_text", True):
        from .ocr import ocr_lines
        lines = [l for l in ocr_lines(ctx.ocr(img, ("ar", "en"))) if l["conf"] > 0.45 and len(l["text"]) > 2]
        if lines:
            txt = ". ".join(l["text"] for l in lines[:6])
            speech += (f" النص المكتوب: {txt}." if ar else f" Text: {txt}.")
    ctx.add_image(out, "What the assistant sees")
    ctx.text(speech, "rtl" if ar else "ltr")
    ctx.result["speak"] = speech
    ctx.result["speak_lang"] = "ar" if ar else "en"
    ctx.stat("Objects", len(dets))
    ctx.stat("Kinds of objects", len(groups))
    ctx.note("Press 'Speak' to hear the description. For a live assistant, run this on camera frames every second or two.")
