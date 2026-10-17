"""Text reading with EasyOCR (Arabic + English) and LaTeX-OCR: documents, plates, IDs, receipts, tables, signs, math."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import cv2
import numpy as np

from ..core import (AMBER, BLUE, GREEN, IMAGE, MEDIA, RED, STRIDE, WHITE, Param, UserError, banner, box, boxes_of, iou,
                    finish_video, frames, is_video, label, pipeline, poly_bbox, video_info, video_output)
from ..registry import ModelError, manager
from .common import prompts_list, to_gray
from .documents import draw_quad, flatten_light, scan

AR_RE = re.compile(r"[؀-ۿ]")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LANGS = Param("langs", "Languages", "multiselect", ["ar", "en"], options=["ar", "en"])


def is_arabic(s: str) -> bool:
    return bool(AR_RE.search(s))


def ocr_lines(items) -> list[dict]:
    """Group EasyOCR word boxes into text lines in reading order (RTL for Arabic lines)."""
    words = [{"box": poly_bbox(b), "text": t, "conf": float(c)} for b, t, c in items if t.strip()]
    words.sort(key=lambda w: (w["box"][1] + w["box"][3]) / 2)
    lines: list[list[dict]] = []
    for w in words:
        cy, hh = (w["box"][1] + w["box"][3]) / 2, w["box"][3] - w["box"][1]
        for ln in lines:
            lcy = np.mean([(x["box"][1] + x["box"][3]) / 2 for x in ln])
            lh = np.mean([x["box"][3] - x["box"][1] for x in ln])
            if abs(cy - lcy) < 0.5 * max(hh, lh):
                ln.append(w)
                break
        else:
            lines.append([w])
    out = []
    for ln in lines:
        rtl = sum(is_arabic(w["text"]) for w in ln) > len(ln) / 2
        ln.sort(key=lambda w: -w["box"][0] if rtl else w["box"][0])
        out.append({"text": " ".join(w["text"] for w in ln), "rtl": rtl, "conf": float(np.mean([w["conf"] for w in ln])),
                    "box": [min(w["box"][0] for w in ln), min(w["box"][1] for w in ln), max(w["box"][2] for w in ln), max(w["box"][3] for w in ln)],
                    "words": ln})
    out.sort(key=lambda l: l["box"][1])
    return out


def draw_ocr(img, lines) -> np.ndarray:
    out = img.copy()
    for ln in lines:
        for w in ln["words"]:
            c = GREEN if w["conf"] > 0.6 else AMBER if w["conf"] > 0.3 else RED
            cv2.rectangle(out, tuple(map(int, w["box"][:2])), tuple(map(int, w["box"][2:])), c, max(2, img.shape[1] // 500))
    return out


def deskew(img: np.ndarray) -> tuple[np.ndarray, float]:
    g = to_gray(img)
    th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    lines = cv2.HoughLinesP(th, 1, np.pi / 360, 120, minLineLength=img.shape[1] // 6, maxLineGap=20)
    if lines is None:
        return img, 0.0
    ang = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4)]
    ang = [a for a in ang if abs(a) < 15]
    if not ang:
        return img, 0.0
    a = float(np.median(ang))
    if abs(a) < 0.3:
        return img, 0.0
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)), a


def _prep(img, ctx):
    page, quad = (scan(img, "color") if ctx.p("find_page", True) else (img, None))
    page, ang = deskew(page) if ctx.p("deskew", True) else (page, 0.0)
    if max(page.shape[:2]) < 1000:
        f = 1000 / max(page.shape[:2])
        page = cv2.resize(page, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return page, quad, ang


# ------------------------------------------------------------------ document OCR

@pipeline("ocr_document", "Document OCR (Arabic + English)",
          "Finds the page, straightens it, and reads Arabic and English text in reading order. Export as TXT and JSON.",
          IMAGE, [LANGS, Param("find_page", "Detect and flatten the page", "bool", True),
                  Param("deskew", "Straighten tilted text", "bool", True)],
          models=["easyocr"])
def ocr_document(ctx):
    img = ctx.image()
    page, quad, ang = _prep(img, ctx)
    langs = tuple(ctx.p("langs", ["ar", "en"]) or ["en"])
    lines = ocr_lines(ctx.ocr(page, langs))
    text = "\n".join(l["text"] for l in lines)
    ctx.add_image(draw_ocr(page, lines), "Recognized words (green = confident)")
    if quad is not None:
        ctx.add_image(draw_quad(img, quad), "Detected page")
    ctx.text(text or "(no text found)", "auto")
    ctx.stat("Lines", len(lines))
    ctx.stat("Words", sum(len(l["words"]) for l in lines))
    ctx.stat("Avg confidence", round(float(np.mean([l["conf"] for l in lines])), 2) if lines else 0)
    ctx.stat("Arabic lines", sum(l["rtl"] for l in lines))
    if abs(ang) > 0:
        ctx.stat("Deskewed", round(ang, 1), unit="°")
    ctx.table("Lines", ["#", "Text", "Direction", "Confidence"],
              [[i + 1, l["text"], "RTL" if l["rtl"] else "LTR", round(l["conf"], 2)] for i, l in enumerate(lines)], "lines.csv")
    ctx.add_file(text.encode("utf-8"), "text.txt")
    ctx.add_json([{"text": l["text"], "rtl": l["rtl"], "confidence": round(l["conf"], 3), "box": [round(v) for v in l["box"]]}
                  for l in lines], "ocr.json")
    if "ar" in langs:
        ctx.note("EasyOCR reads printed Arabic well; handwriting is harder. For handwritten Arabic, fine-tune a recognizer "
                 "(e.g. on the KHATT dataset) and use this pipeline's layout steps around it.")


# ------------------------------------------------------------------ license plates

SAUDI_AR2EN = {"ا": "A", "أ": "A", "ب": "B", "ح": "J", "د": "D", "ر": "R", "س": "S", "ص": "X", "ط": "T", "ع": "E",
               "ق": "G", "ك": "K", "ل": "L", "م": "Z", "ن": "N", "ه": "H", "هـ": "H", "و": "U", "ى": "V", "ي": "V"}


def parse_plate(texts: list[tuple[str, float]], country: str) -> dict:
    raw = " ".join(t for t, _ in texts)
    norm = raw.translate(AR_DIGITS)
    digits = "".join(re.findall(r"\d", norm))
    latin_tokens = [t for t in re.findall(r"[A-Za-z]+", norm.upper()) if t not in ("KSA", "SA", "SAUDI", "KSA.")]
    singles = [t for t in latin_tokens if len(t) == 1]
    latin = "".join(singles) if len(singles) >= 2 else "".join(latin_tokens)
    ar_letters = [c for c in raw if c in SAUDI_AR2EN]
    res = {"raw": raw.strip(), "digits": digits, "letters": latin, "arabic_letters": " ".join(ar_letters)}
    if country == "Saudi Arabia":
        # Saudi plates carry the same number twice (Arabic + Latin digits) and 3 letters in both scripts
        runs = re.findall(r"\d+", norm)
        digits = max(runs, key=len)[:4] if runs else ""  # the number appears in both rows; trust the longest clean run
        from_ar = "".join(SAUDI_AR2EN[c] for c in reversed(ar_letters))[:3]
        letters = latin[:3] if len(latin) >= 3 else from_ar or latin
        res.update(digits=digits, letters=letters, plate=f"{digits} {letters}".strip(),
                   check="letters agree" if from_ar and latin[:3] == from_ar else "")
    else:
        res["plate"] = re.sub(r"\s+", " ", norm).strip()
    return res


def classic_plates(img, max_candidates: int = 6) -> list[dict]:
    """Traditional plate localization: dark characters on a light, wide rectangle with dense vertical edges."""
    g = to_gray(img)
    H, W = g.shape
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)))
    gx = np.absolute(cv2.Sobel(bh, cv2.CV_32F, 1, 0, ksize=3))
    gx = (255 * (gx - gx.min()) / (np.ptp(gx) + 1e-6)).astype(np.uint8)
    gx = cv2.morphologyEx(cv2.GaussianBlur(gx, (5, 5), 0), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5)))
    th = cv2.threshold(gx, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    th = cv2.dilate(cv2.erode(th, None, iterations=2), None, iterations=2)
    light = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    cands = []
    for c in cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(c)
        if not (1.8 <= w / max(h, 1) <= 6.5 and W * 0.04 < w < W * 0.6 and h > 14):
            continue
        roi_light = light[y:y + h, x:x + w].mean() / 255
        edge = th[y:y + h, x:x + w].mean() / 255
        if roi_light < 0.35:
            continue
        # two-row plates (Arabic over Latin) are often found one row at a time: include the neighbouring row
        y1, y2 = max(0, int(y - 0.7 * h)), min(H, int(y + 1.7 * h))
        cands.append({"box": [x, y1, x + w, y2], "conf": round(float(0.5 * edge + 0.5 * roi_light), 3), "cls": "plate"})
    keep = []
    for d in sorted(cands, key=lambda d: -d["conf"]):
        if all(iou(d["box"], k["box"]) < 0.3 for k in keep):
            keep.append(d)
    return keep[:max_candidates]


@pipeline("plate_recognition", "License plate recognition (ALPR)",
          "Detects plates with a public YOLO26 plate model (or YOLOE-26 as a fallback), then reads Arabic and English characters. "
          "Saudi plates are normalized to '1234 ABJ' format.",
          MEDIA, [Param("country", "Plate format", "select", "Saudi Arabia", options=["Saudi Arabia", "Generic"]),
                  Param("conf", "Plate confidence", "number", 0.25, 0.05, 0.9, 0.05),
                  Param("stride", "Video: read every Nth frame", "int", 5, 1, 30, 1, advanced=True)],
          models=["plate-yolo26", "yoloe26", "easyocr"], custom_task="detect")
def plate_recognition(ctx):
    country = ctx.p("country", "Saudi Arabia")
    conf = float(ctx.p("conf", 0.25))
    key = ctx.model_key("plate-yolo26")
    try:
        manager.get(key)
        detector = key
    except ModelError as e:
        detector = None
        ctx.note(f"Public plate model unavailable ({e}). Using YOLOE-26 with the prompt 'license plate'.")

    def find_plates(img):
        h, w = img.shape[:2]
        if 1.8 < w / h < 6 and max(h, w) < 900:   # the image is already a cropped plate
            return [{"box": [0, 0, w, h], "conf": 1.0, "cls": "plate"}]
        if detector:
            found = boxes_of(ctx.predict(detector, img, conf=conf)[0])
        else:
            found = boxes_of(ctx.yoloe(["license plate"], img, conf=max(0.1, conf - 0.1))[0])
        if not found:
            found = classic_plates(img)
            if found:
                ctx.note("Plates were located with the classical edge-based method; the OCR check filters false candidates.")
        return found

    def read(img, d):
        x1, y1, x2, y2 = d["box"]
        px, py = 0.06 * (x2 - x1), 0.12 * (y2 - y1)
        crop = img[max(0, int(y1 - py)):int(y2 + py), max(0, int(x1 - px)):int(x2 + px)]
        if crop.size == 0:
            return None, None
        crop = cv2.resize(crop, None, fx=200 / max(1, crop.shape[0]), fy=200 / max(1, crop.shape[0]), interpolation=cv2.INTER_CUBIC)
        items = ctx.ocr(crop, ("ar", "en") if country == "Saudi Arabia" else ("en",))
        texts = [(t, c) for _, t, c in items]
        res = parse_plate(texts, country)
        res["conf"] = float(np.mean([c for _, c in texts])) if texts else 0.0
        return res, crop

    f = ctx.file()
    if not is_video(f):
        img = f.read()
        out = img.copy()
        rows = []
        for i, d in enumerate(find_plates(img)):
            res, crop = read(img, d)
            if res is None or len(re.sub(r"\W", "", res["raw"])) < 3:
                continue  # not a plate: too little text
            if country == "Saudi Arabia" and len(res["digits"]) < 3:
                continue  # Saudi plates always carry at least 3 digits
            box(out, d["box"], res["plate"] or "?", GREEN if res["plate"] else AMBER)
            rows.append([i + 1, res["plate"], res["digits"], res["letters"], res.get("arabic_letters", ""), res["raw"],
                         round(d["conf"], 2), round(res["conf"], 2)])
            if i < 6:
                ctx.add_image(crop, f"Plate {i + 1}: {res['plate']}")
        ctx.result["images"].insert(0, {"url": ctx.add_image(out, "Plates"), "caption": "Plates"})
        ctx.result["images"].pop()
        ctx.stat("Plates", len(rows), "good" if rows else "warn")
        if rows:
            ctx.stat("First plate", rows[0][1] or "unreadable")
            ctx.table("Plates", ["#", "Plate", "Digits", "Letters", "Arabic letters", "Raw OCR", "Detect conf", "OCR conf"], rows, "plates.csv")
        else:
            ctx.note("No plate found. Plates should be at least ~80 px wide in the image.")
        return
    info = video_info(f.path)
    stride = int(ctx.p("stride", 5))
    writer = video_output(ctx, info.fps / stride)
    votes: dict[str, Counter] = defaultdict(Counter)
    first_seen: dict[str, float] = {}
    for i, t, img in frames(f.path, stride):
        out = img.copy()
        for d in find_plates(img):
            res, _ = read(img, d)
            if res and len(res["plate"]) >= 4:
                votes[res["plate"]][res["plate"]] += 1
                first_seen.setdefault(res["plate"], round(t, 1))
                box(out, d["box"], res["plate"], GREEN)
        writer.write(out)
        ctx.progress(i / max(1, info.frames))
    finish_video(ctx, writer, "Plate reading")
    rows = sorted([[p, sum(c.values()), first_seen[p]] for p, c in votes.items()], key=lambda r: -r[1])
    ctx.stat("Distinct plates", len(rows))
    if rows:
        ctx.table("Plates seen", ["Plate", "Frames read", "First seen (s)"], rows, "plates.csv")


# ------------------------------------------------------------------ ID card fields

ID_LABELS = {
    "name": ["name", "full name", "الاسم", "اسم"],
    "id_number": ["id no", "id number", "id", "number", "no", "رقم الهوية", "رقم"],
    "date_of_birth": ["date of birth", "dob", "birth", "تاريخ الميلاد", "الميلاد"],
    "expiry": ["expiry", "expiration", "expires", "valid until", "تاريخ الانتهاء", "الانتهاء"],
    "nationality": ["nationality", "الجنسية"],
    "sex": ["sex", "gender", "الجنس"],
}
DATE_RE = re.compile(r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}|\d{1,2}[/.\-]\d{4})\b")


@pipeline("id_card", "ID card information extraction",
          "Flattens the card, reads it in Arabic and English, and pulls out fields such as name, ID number and dates.",
          IMAGE, [LANGS, Param("find_page", "Detect and flatten the card", "bool", True), Param("deskew", "Straighten", "bool", False)],
          models=["easyocr"])
def id_card(ctx):
    img = ctx.image()
    page, quad, _ = _prep(img, ctx)
    items = ctx.ocr(page, tuple(ctx.p("langs", ["ar", "en"]) or ["en"]))
    words = [{"box": poly_bbox(b), "text": t.strip(), "conf": float(c)} for b, t, c in items if t.strip()]
    fields: dict[str, tuple[str, float]] = {}
    for w in words:
        low = w["text"].lower().rstrip(":").strip()
        for field, labels in ID_LABELS.items():
            if field in fields:
                continue
            hit = next((lb for lb in labels if low == lb or low.startswith(lb + ":") or (len(lb) > 3 and low.startswith(lb))), None)
            if not hit:
                continue
            rest = w["text"][len(hit):].lstrip(" :")
            if len(rest) > 1:
                fields[field] = (rest, w["conf"])
                break
            cy, h = (w["box"][1] + w["box"][3]) / 2, w["box"][3] - w["box"][1]
            rtl = is_arabic(w["text"])
            same_line = [v for v in words if v is not w and abs((v["box"][1] + v["box"][3]) / 2 - cy) < 0.6 * h
                         and ((v["box"][2] <= w["box"][0]) if rtl else (v["box"][0] >= w["box"][2]))]
            if same_line:
                v = min(same_line, key=lambda v: abs(v["box"][0] - w["box"][2]) if not rtl else abs(w["box"][0] - v["box"][2]))
                fields[field] = (v["text"], v["conf"])
            break
    all_text = " ".join(w["text"] for w in words).translate(AR_DIGITS)
    dates = DATE_RE.findall(all_text)
    if "date_of_birth" not in fields and dates:
        fields["date_of_birth"] = (dates[0], 0.0)
    if "expiry" not in fields and len(dates) > 1:
        fields["expiry"] = (dates[-1], 0.0)
    if "id_number" not in fields:
        m = re.search(r"\b\d{8,12}\b", all_text)
        if m:
            fields["id_number"] = (m.group(0), 0.0)
    lines = ocr_lines(items)
    ctx.add_image(draw_ocr(page, lines), "Card (recognized words)")
    ctx.stat("Fields found", len(fields), "good" if len(fields) >= 3 else "warn")
    for k in ("name", "id_number", "date_of_birth", "expiry"):
        if k in fields:
            ctx.stat(k.replace("_", " ").capitalize(), fields[k][0])
    ctx.table("Fields", ["Field", "Value", "OCR confidence"], [[k.replace("_", " "), v, round(c, 2) if c else "pattern match"]
                                                               for k, (v, c) in fields.items()], "fields.csv")
    ctx.add_json({k: v for k, (v, _) in fields.items()}, "fields.json")
    ctx.text("\n".join(l["text"] for l in lines))
    ctx.note("ID data is personal. Process only cards you're authorized to handle, and don't store images longer than needed.")


# ------------------------------------------------------------------ receipts

MONEY_PATTERNS = [re.compile(r"(\d+)\s?[.,]\s?(\d{2})\s*$"),             # 13.00 · 79. 65 · 6,50
                  re.compile(r"(?<![\d.,])(\d{1,4})\s(\d{2})\s*$")]       # 28 90 (OCR dropped the point)


def _money_match(s: str):
    s = re.sub(r"(\d),(\d{3})(?=[.,]\d{2}\s*$)", r"\1\2", s.translate(AR_DIGITS))
    for pat in MONEY_PATTERNS:
        m = pat.search(s)
        if m:
            return m, s
    return None, s


def _money(s: str) -> float | None:
    m, _ = _money_match(s)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


@pipeline("receipt", "Receipt and invoice scanner",
          "Reads a receipt and extracts the date, line items, tax and total. Download the items as CSV (opens in Excel).",
          IMAGE, [Param("langs", "Languages", "multiselect", ["en"], options=["ar", "en"]),
                  Param("find_page", "Detect and flatten the receipt", "bool", True), Param("deskew", "Straighten", "bool", True)],
          models=["easyocr"])
def receipt(ctx):
    img = ctx.image()
    page, quad, _ = _prep(img, ctx)
    lines = ocr_lines(ctx.ocr(page, tuple(ctx.p("langs", ["en"]) or ["en"])))
    total = subtotal = tax = None
    items, date = [], None
    for ln in lines:
        t = ln["text"]
        low = t.lower()
        amt = _money(t)
        if date is None:
            m = DATE_RE.search(t.translate(AR_DIGITS))
            if m:
                date = m.group(1)
        if amt is None:
            continue
        if re.search(r"sub\s*-?\s*total|المجموع الفرعي", low):
            subtotal = amt
        elif re.search(r"vat|tax|ضريبة", low):
            tax = amt
        elif re.search(r"total|grand|amount due|الإجمالي|المجموع|الاجمالي", low):
            total = amt
        elif not re.search(r"cash|change|card|visa|paid|balance|invoice|tel|phone", low):
            m, norm = _money_match(t)
            name = norm[:m.start()].strip(" .:-")
            qty = 1
            mq = re.search(r"\b(\d+)\s*[xX×]\s*[\d]+\s?[.,]?\s?\d*\s*$", name)
            if mq:
                qty = int(mq.group(1))
                name = name[:mq.start()].strip()
            if name:
                items.append([name, qty, amt])
    if total is None and items:
        total = max(r[2] for r in items)
    ctx.add_image(draw_ocr(page, lines), "Receipt (recognized words)")
    ctx.stat("Total", f"{total:.2f}" if total is not None else "not found", "good" if total is not None else "warn")
    if subtotal is not None:
        ctx.stat("Subtotal", f"{subtotal:.2f}")
    if tax is not None:
        ctx.stat("Tax", f"{tax:.2f}")
    ctx.stat("Date", date or "not found")
    ctx.stat("Line items", len(items))
    ctx.table("Line items", ["Item", "Qty", "Line total"], items, "receipt_items.csv")
    if items and total is not None:
        s = round(sum(r[2] for r in items), 2)
        base = subtotal if subtotal is not None else total
        ctx.note(f"Items add up to {s:.2f}; the receipt says {base:.2f}." + (" ✓" if abs(s - base) < 0.05 else " Check the items list."))
    ctx.add_json({"date": date, "subtotal": subtotal, "tax": tax, "total": total,
                  "items": [{"name": a, "qty": b, "amount": c} for a, b, c in items]}, "receipt.json")
    ctx.text("\n".join(l["text"] for l in lines))


# ------------------------------------------------------------------ tables

@pipeline("table_extraction", "Table structure recognition",
          "Finds the table grid, reads each cell, and exports the table as CSV for Excel.",
          IMAGE, [LANGS, Param("find_page", "Detect and flatten the page", "bool", False), Param("deskew", "Straighten", "bool", True)],
          models=["easyocr"])
def table_extraction(ctx):
    img = ctx.image()
    page, _, _ = _prep(img, ctx)
    g = to_gray(page)
    th = cv2.adaptiveThreshold(~g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    H, W = th.shape
    hor = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, W // 25), 1)))
    ver = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, H // 25))))

    def positions(profile, min_gap):
        idx = np.where(profile > profile.max() * 0.35)[0] if profile.max() > 0 else []
        groups, cur = [], []
        for i in idx:
            if cur and i - cur[-1] > min_gap:
                groups.append(int(np.mean(cur)))
                cur = []
            cur.append(i)
        if cur:
            groups.append(int(np.mean(cur)))
        return groups

    ys = positions(hor.sum(1).astype(float), 8)
    xs = positions(ver.sum(0).astype(float), 8)
    langs = tuple(ctx.p("langs", ["ar", "en"]) or ["en"])
    out = page.copy()
    grid = []
    if len(ys) >= 2 and len(xs) >= 2:
        for r in range(len(ys) - 1):
            row = []
            for c in range(len(xs) - 1):
                y1, y2, x1, x2 = ys[r] + 3, ys[r + 1] - 3, xs[c] + 3, xs[c + 1] - 3
                cell = page[y1:y2, x1:x2]
                txt = ""
                if cell.size and (255 - to_gray(cell)).mean() > 3:
                    items = ctx.ocr(cv2.copyMakeBorder(cell, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255)), langs)
                    txt = " ".join(l["text"] for l in ocr_lines(items))
                row.append(txt)
                cv2.rectangle(out, (x1, y1), (x2, y2), GREEN if txt else (180, 180, 180), 2)
            grid.append(row)
            ctx.progress((r + 1) / (len(ys) - 1))
        mode = "ruled"
    else:
        # no ruling lines: cluster words into rows and columns
        lines = ocr_lines(ctx.ocr(page, langs))
        xs_all = sorted({round(w["box"][0] / 40) * 40 for l in lines for w in l["words"]})
        cols: list[float] = []
        for x in xs_all:
            if not cols or x - cols[-1] > 60:
                cols.append(x)
        for l in lines:
            row = [""] * len(cols)
            for w in sorted(l["words"], key=lambda w: w["box"][0]):
                ci = int(np.argmin([abs(w["box"][0] - c) for c in cols]))
                row[ci] = (row[ci] + " " + w["text"]).strip()
            grid.append(row)
            cv2.rectangle(out, tuple(map(int, l["box"][:2])), tuple(map(int, l["box"][2:])), AMBER, 2)
        mode = "borderless"
    if not grid:
        raise UserError("Couldn't find a table.")
    header, body = grid[0], grid[1:]
    ctx.add_image(out, "Detected cells")
    ctx.stat("Rows", len(grid))
    ctx.stat("Columns", max(len(r) for r in grid))
    ctx.stat("Layout", mode)
    cols = [h or f"Column {i + 1}" for i, h in enumerate(header)]
    ctx.table("Extracted table", cols, body, "table.csv")


# ------------------------------------------------------------------ whiteboard

@pipeline("whiteboard_capture", "Smart whiteboard capture",
          "Finds the board, corrects the perspective, whitens the background, boosts marker colors and optionally reads the text.",
          IMAGE, [Param("ocr", "Read the text", "bool", True), Param("langs", "Languages", "multiselect", ["en"], options=["ar", "en"])],
          models=["easyocr"])
def whiteboard_capture(ctx):
    img = ctx.image()
    page, quad = scan(img, "original")
    flat = flatten_light(page)
    hsv = cv2.cvtColor(flat, cv2.COLOR_BGR2HSV)
    hsv[..., 1] = cv2.multiply(hsv[..., 1], 1.8)
    clean = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    clean[cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY) > 225] = 255
    ctx.add_image(clean, "Enhanced board")
    ctx.add_image(draw_quad(img, quad), "Detected board")
    ctx.stat("Board found", "yes" if quad is not None else "no", "good" if quad is not None else "warn")
    if ctx.p("ocr", True):
        lines = ocr_lines(ctx.ocr(clean, tuple(ctx.p("langs", ["en"]) or ["en"])))
        ctx.text("\n".join(l["text"] for l in lines) or "(no text found)")
        ctx.stat("Text lines", len(lines))
        ctx.add_file("\n".join(l["text"] for l in lines).encode("utf-8"), "board_notes.txt")
    try:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.fromarray(cv2.cvtColor(clean, cv2.COLOR_BGR2RGB)).save(buf, "PDF", resolution=150)
        ctx.add_file(buf.getvalue(), "board.pdf")
    except Exception:
        pass


# ------------------------------------------------------------------ road signs

def sign_shape(crop) -> str:
    g = cv2.GaussianBlur(to_gray(crop), (5, 5), 0)
    th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return "unknown"
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.2 * crop.shape[0] * crop.shape[1]:
        return "unknown"
    n = len(cv2.approxPolyDP(c, 0.03 * cv2.arcLength(c, True), True))
    return {3: "triangle", 4: "rectangle", 8: "octagon"}.get(n, "circle" if n > 8 else f"{n}-sided")


@pipeline("road_sign_reader", "Road sign detection and reading",
          "Finds traffic signs with YOLOE-26, describes their shape and color, and reads Arabic/English text on them.",
          IMAGE, [Param("prompts", "Signs to look for", "text", "traffic sign, stop sign, road sign, speed limit sign"),
                  Param("conf", "Confidence threshold", "number", 0.15, 0.05, 0.9, 0.05), LANGS],
          models=["yoloe26", "easyocr"])
def road_sign_reader(ctx):
    from .common import dominant_color
    img = ctx.image()
    dets = boxes_of(ctx.yoloe(prompts_list(ctx.p("prompts")), img, conf=float(ctx.p("conf", 0.15)))[0])
    out = img.copy()
    rows = []
    for i, d in enumerate(dets):
        x1, y1, x2, y2 = map(int, d["box"])
        crop = img[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            continue
        big = cv2.resize(crop, None, fx=max(1, 160 / crop.shape[0]), fy=max(1, 160 / crop.shape[0]), interpolation=cv2.INTER_CUBIC)
        txt = " ".join(l["text"] for l in ocr_lines(ctx.ocr(big, tuple(ctx.p("langs", ["ar", "en"]) or ["en"]))))
        color, _ = dominant_color(crop)
        shape = sign_shape(crop)
        speed = re.search(r"\b(\d{2,3})\b", txt.translate(AR_DIGITS))
        rows.append([i + 1, d["cls"], shape, color, txt, speed.group(1) if speed and "speed" in d["cls"] else "", round(d["conf"], 2)])
        box(out, d["box"], f"{d['cls']}: {txt[:24]}" if txt else d["cls"], AMBER)
    ctx.add_image(out, "Signs")
    ctx.stat("Signs", len(rows))
    if rows:
        ctx.table("Signs", ["#", "Type", "Shape", "Color", "Text", "Speed limit", "Confidence"], rows, "signs.csv")
    ctx.note("Zero-shot detection. For a production system, train YOLO26 on a regional sign dataset with one class per sign.")


# ------------------------------------------------------------------ math

@pipeline("math_ocr", "Math formula recognition",
          "Converts formulas to LaTeX with LaTeX-OCR. Each line of an image is read separately.",
          IMAGE, [Param("split_lines", "Split into lines", "bool", True)], models=["latex-ocr"])
def math_ocr(ctx):
    from PIL import Image
    img = ctx.image()
    g = to_gray(img)
    th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    bands = [(0, img.shape[0])]
    if ctx.p("split_lines", True):
        prof = th.sum(1) > 0
        bands, start = [], None
        for y, v in enumerate(list(prof) + [False]):
            if v and start is None:
                start = y
            elif not v and start is not None:
                if y - start > 12:
                    bands.append((max(0, start - 8), min(img.shape[0], y + 8)))
                start = None
        bands = bands or [(0, img.shape[0])]
    results = []
    with manager.use("latex-ocr") as model:
        for i, (y1, y2) in enumerate(bands[:20]):
            crop = img[y1:y2]
            cols = np.where(th[y1:y2].sum(0) > 0)[0]
            if len(cols):
                crop = crop[:, max(0, cols[0] - 10):cols[-1] + 10]
            latex = model(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            results.append(latex)
            ctx.progress((i + 1) / len(bands))
    out = img.copy()
    for (y1, y2) in bands:
        cv2.rectangle(out, (2, y1), (out.shape[1] - 3, y2), AMBER, 2)
    ctx.add_image(out, "Formula lines")
    ctx.stat("Formulas", len(results))
    ctx.result["latex"] = results
    ctx.text("\n".join(results))
    ctx.table("LaTeX", ["#", "LaTeX"], [[i + 1, r] for i, r in enumerate(results)], "formulas.csv")
    ctx.add_file("\n".join(results).encode(), "formulas.tex")
    ctx.note("Works best on printed or neatly written formulas, one per line.")
