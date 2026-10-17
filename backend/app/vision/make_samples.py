"""Generate the sample inputs used by "Try sample" buttons and by the pipeline tests.

    python -m app.vision.make_samples

bus.jpg and zidane.jpg come from the Ultralytics repository; everything else is drawn here,
so it carries no third-party rights. All people, IDs and plates are fictional.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "samples"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
rng = np.random.default_rng(7)


def font(size, path=FONT):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def text(draw, xy, s, size, fill=(20, 20, 20), path=FONT, rtl=False, anchor=None):
    kw = {"direction": "rtl", "language": "ar"} if rtl else {}
    draw.text(xy, s, fill=fill, font=font(size, path), anchor=anchor, **kw)


def to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def save(name, img):
    cv2.imwrite(str(OUT / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])


def on_table(page: np.ndarray, out_w=1200, out_h=900, tilt=0.06, bg=(70, 92, 120)) -> np.ndarray:
    """Place a page on a textured surface with perspective."""
    h, w = page.shape[:2]
    canvas = np.full((out_h, out_w, 3), bg, np.uint8)
    noise = rng.normal(0, 9, (out_h, out_w, 1)).astype(np.int16)
    canvas = np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    s = min(out_w * 0.72 / w, out_h * 0.85 / h)
    pw, ph = w * s, h * s
    cx, cy = out_w / 2, out_h / 2
    dst = np.float32([[cx - pw / 2 + pw * tilt, cy - ph / 2], [cx + pw / 2 - pw * tilt * 0.4, cy - ph / 2 + ph * tilt * 0.5],
                      [cx + pw / 2 + pw * tilt * 0.3, cy + ph / 2], [cx - pw / 2 - pw * tilt * 0.2, cy + ph / 2 - ph * tilt * 0.3]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst)
    warped = cv2.warpPerspective(page, M, (out_w, out_h))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (out_w, out_h))
    shade = np.linspace(1.0, 0.82, out_w)[None, :, None]
    canvas[mask > 0] = (warped[mask > 0] * shade.repeat(out_h, 0)[mask > 0]).astype(np.uint8)
    return canvas


# ------------------------------------------------------------------ documents

def document():
    img = Image.new("RGB", (900, 1200), (250, 249, 245))
    d = ImageDraw.Draw(img)
    text(d, (850, 60), "تقرير التفتيش الشهري", 44, rtl=True, anchor="ra", path=FONT_B)
    text(d, (60, 130), "Monthly Inspection Report", 34, path=FONT_B)
    lines_ar = ["تم فحص جميع الكاميرات في المستودع الرئيسي", "عدد المركبات المسجلة اليوم ٢٤٥ مركبة",
                "يرجى مراجعة تقرير السلامة قبل نهاية الأسبوع"]
    for i, ln in enumerate(lines_ar):
        text(d, (850, 220 + i * 62), ln, 32, rtl=True, anchor="ra")
    lines_en = ["All cameras in the main warehouse were inspected.", "Vehicles registered today: 245",
                "Please review the safety report before Thursday.", "Prepared by: Operations Team", "Date: 2026-10-15"]
    for i, ln in enumerate(lines_en):
        text(d, (60, 450 + i * 56), ln, 30)
    d.rectangle([60, 780, 840, 784], fill=(40, 40, 40))
    text(d, (60, 810), "Reference: VA-2026-118", 28, path=MONO)
    save("document.jpg", on_table(to_cv(img)))
    save("document_flat.jpg", to_cv(img))


def receipt():
    img = Image.new("RGB", (560, 980), (252, 252, 250))
    d = ImageDraw.Draw(img)
    text(d, (280, 40), "ATLAS MARKET", 38, anchor="ma", path=FONT_B)
    text(d, (280, 92), "King Fahd Rd, Riyadh", 22, anchor="ma")
    text(d, (40, 150), "Date: 14/10/2026   Time: 18:42", 24, path=MONO)
    text(d, (40, 186), "Invoice: 000482", 24, path=MONO)
    items = [("Milk 1L", 2, 6.50), ("Bread", 1, 4.00), ("Apples 1kg", 1, 9.75), ("Water 6x", 2, 12.00), ("Coffee", 1, 28.90)]
    y = 250
    for name, q, p in items:
        text(d, (40, y), f"{name:<14}{q:>2} x {p:>6.2f}", 24, path=MONO)
        text(d, (520, y), f"{q * p:.2f}", 24, path=MONO, anchor="ra")
        y += 44
    sub = sum(q * p for _, q, p in items)
    d.line([40, y + 10, 520, y + 10], fill=(30, 30, 30), width=2)
    for label, val in (("Subtotal", sub), ("VAT 15%", sub * 0.15), ("TOTAL", sub * 1.15)):
        y += 50
        text(d, (40, y), label, 28 if label == "TOTAL" else 24, path=FONT_B if label == "TOTAL" else MONO)
        text(d, (520, y), f"{val:.2f}", 28 if label == "TOTAL" else 24, path=FONT_B if label == "TOTAL" else MONO, anchor="ra")
    text(d, (280, y + 90), "Thank you", 24, anchor="ma")
    save("receipt.jpg", on_table(to_cv(img), 1000, 1100, 0.03, (40, 40, 45)))


def id_card():
    img = Image.new("RGB", (1000, 630), (232, 240, 247))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1000, 90], fill=(36, 70, 160))
    text(d, (30, 22), "ATLAS DEMO ID — SPECIMEN", 36, (255, 255, 255), FONT_B)
    text(d, (970, 24), "بطاقة تجريبية", 34, (255, 255, 255), rtl=True, anchor="ra")
    d.rectangle([40, 130, 300, 460], fill=(200, 210, 222), outline=(120, 130, 150), width=3)
    text(d, (170, 280), "PHOTO", 36, (120, 130, 150), anchor="ma")
    fields = [("Name", "Sara Al-Demo"), ("ID No", "1098765432"), ("Date of Birth", "03/07/1995"),
              ("Expiry", "12/2030"), ("Nationality", "Demo")]
    for i, (k, v) in enumerate(fields):
        text(d, (340, 140 + i * 70), k, 24, (90, 100, 120))
        text(d, (560, 136 + i * 70), v, 32, (20, 20, 30), FONT_B)
    text(d, (960, 520), "الاسم: سارة التجريبية", 30, rtl=True, anchor="ra")
    text(d, (40, 560), "SPECIMEN - NOT A REAL DOCUMENT", 22, (180, 40, 40), FONT_B)
    save("id_card.jpg", on_table(to_cv(img), 1300, 1000, 0.05, (55, 60, 66)))


def whiteboard():
    img = Image.new("RGB", (1200, 800), (246, 247, 244))
    d = ImageDraw.Draw(img)
    text(d, (60, 60), "Sprint plan", 64, (30, 60, 160), FONT_B)
    for i, ln in enumerate(["1. Label 500 plate images", "2. Train YOLO26n  (100 epochs)", "3. Export ONNX + test on CPU",
                            "4. Demo on Thursday"]):
        text(d, (80, 190 + i * 110), ln, 52, (25, 25, 25))
    d.ellipse([880, 470, 1120, 700], outline=(200, 40, 40), width=8)
    text(d, (920, 560), "mAP?", 52, (200, 40, 40))
    board = to_cv(img)
    save("whiteboard.jpg", on_table(board, 1400, 1000, 0.08, (150, 145, 135)))


def table_doc():
    rows = [["Camera", "Location", "Status", "Uptime"], ["CAM-01", "Gate A", "Online", "99.2%"], ["CAM-02", "Warehouse", "Online", "97.8%"],
            ["CAM-03", "Parking", "Offline", "61.0%"], ["CAM-04", "Loading", "Online", "98.5%"], ["CAM-05", "Office", "Online", "99.9%"]]
    W, H, cw, rh = 1000, 520, 240, 76
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x0, y0 = 20, 30
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            text(d, (x0 + c * cw + 16, y0 + r * rh + 20), cell, 28, path=FONT_B if r == 0 else FONT)
    for r in range(len(rows) + 1):
        d.line([x0, y0 + r * rh, x0 + 4 * cw, y0 + r * rh], fill=(0, 0, 0), width=3)
    for c in range(5):
        d.line([x0 + c * cw, y0, x0 + c * cw, y0 + len(rows) * rh], fill=(0, 0, 0), width=3)
    save("table.jpg", to_cv(img))


def math_img():
    img = Image.new("RGB", (900, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    text(d, (40, 50), "E = m c²   ,   a² + b² = c²", 64)
    save("math.jpg", to_cv(img))


def qr_codes():
    canvas = np.full((800, 1100, 3), 245, np.uint8)
    enc = cv2.QRCodeEncoder.create()
    qr = enc.encode("https://example.com/asset/CAM-03")
    qr = cv2.resize(qr, (360, 360), interpolation=cv2.INTER_NEAREST)
    canvas[80:440, 80:440] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
    # EAN-13 barcode
    code = "629104150021"
    digits = [int(c) for c in code]
    check = (10 - (sum(digits[0::2]) + 3 * sum(digits[1::2])) % 10) % 10
    digits.append(check)
    L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
    G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
    R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
    PAR = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]
    bits = "101" + "".join((L if p == "L" else G)[d] for p, d in zip(PAR[digits[0]], digits[1:7])) + "01010" + "".join(R[d] for d in digits[7:]) + "101"
    m = 5
    bc = np.full((260, len(bits) * m + 40, 3), 255, np.uint8)
    for i, b in enumerate(bits):
        if b == "1":
            bc[20:230, 20 + i * m:20 + (i + 1) * m] = 0
    canvas[120:380, 520:520 + bc.shape[1]] = bc
    cv2.putText(canvas, "".join(map(str, digits)), (560, 420), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2, cv2.LINE_AA)
    M = cv2.getRotationMatrix2D((550, 400), 8, 1.0)
    canvas = cv2.warpAffine(canvas, M, (1100, 800), borderValue=(245, 245, 245))
    save("codes.jpg", canvas)


def omr():
    W, H = 850, 1100
    img = np.full((H, W, 3), 255, np.uint8)
    cv2.putText(img, "ANSWER SHEET", (250, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
    answers = [1, 4, 0, 3, 1, 2, 0, 4]
    for q, a in enumerate(answers):
        y = 200 + q * 105
        cv2.putText(img, f"{q + 1}.", (90, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
        for o in range(5):
            x = 220 + o * 115
            cv2.circle(img, (x, y), 34, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, "ABCDE"[o], (x - 11, y + 11), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (150, 150, 150), 2, cv2.LINE_AA)
            if o == a:
                cv2.circle(img, (x, y), 27, (25, 25, 25), -1, cv2.LINE_AA)
    save("omr.jpg", on_table(img, 1200, 1300, 0.04, (60, 75, 90)))


def gauge(value=62):
    S = 700
    img = np.full((S, S, 3), (215, 218, 222), np.uint8)
    c = (S // 2, S // 2)
    cv2.circle(img, c, 300, (60, 60, 60), 18, cv2.LINE_AA)
    cv2.circle(img, c, 288, (250, 250, 250), -1, cv2.LINE_AA)
    a0, a1 = 225, -45  # 0 at 225°, 100 at -45° (counter-clockwise from +x, y up)
    for v in range(0, 101, 5):
        a = math.radians(a0 + (a1 - a0) * v / 100)
        r1, r2 = 270, 230 if v % 10 == 0 else 250
        p1 = (int(c[0] + r1 * math.cos(a)), int(c[1] - r1 * math.sin(a)))
        p2 = (int(c[0] + r2 * math.cos(a)), int(c[1] - r2 * math.sin(a)))
        cv2.line(img, p1, p2, (30, 30, 30), 5 if v % 10 == 0 else 2, cv2.LINE_AA)
        if v % 20 == 0:
            pt = (int(c[0] + 190 * math.cos(a)) - 22, int(c[1] - 190 * math.sin(a)) + 12)
            cv2.putText(img, str(v), pt, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(img, "bar", (c[0] - 30, c[1] + 140), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (60, 60, 60), 2, cv2.LINE_AA)
    a = math.radians(a0 + (a1 - a0) * value / 100)
    tip = (int(c[0] + 250 * math.cos(a)), int(c[1] - 250 * math.sin(a)))
    tail = (int(c[0] - 40 * math.cos(a)), int(c[1] + 40 * math.sin(a)))
    cv2.line(img, tail, tip, (30, 30, 200), 10, cv2.LINE_AA)
    cv2.circle(img, c, 24, (40, 40, 40), -1, cv2.LINE_AA)
    save("gauge.jpg", img)


# ------------------------------------------------------------------ industrial / science

def concrete(h, w, base=150):
    tex = rng.normal(base, 18, (h, w)).astype(np.float32)
    tex = cv2.GaussianBlur(tex, (0, 0), 1.2) + cv2.GaussianBlur(rng.normal(0, 25, (h, w)).astype(np.float32), (0, 0), 18)
    return np.clip(tex, 0, 255).astype(np.uint8)


def crack():
    h, w = 800, 1100
    g = concrete(h, w)
    x, y = 60.0, 200.0
    pts = []
    while x < w - 40:
        x += rng.uniform(4, 9)
        y += rng.normal(0, 4) + 1.2
        pts.append((int(x), int(y)))
    for i in range(1, len(pts)):
        wdt = int(2 + 4 * abs(math.sin(i / 25)))
        cv2.line(g, pts[i - 1], pts[i], 45, wdt, cv2.LINE_AA)
    b = pts[len(pts) // 2]
    for _ in range(60):
        nb = (b[0] + int(rng.uniform(2, 7)), b[1] + int(rng.uniform(3, 8)))
        cv2.line(g, b, nb, 55, 2, cv2.LINE_AA)
        b = nb
    save("crack.jpg", cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))


def particles():
    h, w = 900, 1200
    img = np.full((h, w), 225, np.float32) + rng.normal(0, 6, (h, w))
    for _ in range(85):
        cx, cy = rng.uniform(30, w - 30), rng.uniform(30, h - 30)
        a, b = rng.uniform(6, 28), rng.uniform(6, 28)
        cv2.ellipse(img, (int(cx), int(cy)), (int(a), int(b)), rng.uniform(0, 180), 0, 360, float(rng.uniform(40, 90)), -1, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 1.3)
    save("particles.jpg", cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR))


def cells():
    h, w = 900, 1200
    img = np.zeros((h, w, 3), np.float32)
    img[:] = (205, 190, 238)
    placed = []
    for _ in range(400):
        r = rng.uniform(24, 30)
        cx, cy = rng.uniform(r, w - r), rng.uniform(r, h - r)
        if all((cx - x) ** 2 + (cy - y) ** 2 > (r + rr - 6) ** 2 for x, y, rr in placed):
            placed.append((cx, cy, r))
        if len(placed) >= 110:
            break
    for cx, cy, r in placed:
        cv2.circle(img, (int(cx), int(cy)), int(r), (120, 95, 205), -1, cv2.LINE_AA)
        cv2.circle(img, (int(cx), int(cy)), int(r * 0.45), (165, 140, 225), -1, cv2.LINE_AA)
    for _ in range(4):
        cx, cy = rng.uniform(60, w - 60), rng.uniform(60, h - 60)
        cv2.circle(img, (int(cx), int(cy)), 46, (160, 80, 110), -1, cv2.LINE_AA)
        for k in range(3):
            cv2.circle(img, (int(cx + rng.uniform(-18, 18)), int(cy + rng.uniform(-18, 18))), 16, (140, 40, 90), -1, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 1.5) + rng.normal(0, 4, img.shape)
    save("cells.jpg", np.clip(img, 0, 255).astype(np.uint8))


def fabric():
    h, w = 800, 1000
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    weave = 128 + 45 * np.sin(xx / 3.2) * np.sin(yy / 3.2) + 25 * np.sin((xx + yy) / 9)
    weave += rng.normal(0, 6, (h, w))
    img = cv2.cvtColor(np.clip(weave, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    img = (img * np.array([0.75, 0.62, 0.45])).astype(np.uint8)
    cv2.ellipse(img, (620, 330), (34, 22), 20, 0, 360, (25, 25, 30), -1, cv2.LINE_AA)        # hole
    cv2.line(img, (200, 560), (420, 575), (170, 150, 120), 5, cv2.LINE_AA)                     # broken thread
    cv2.circle(img, (300, 200), 40, (60, 75, 110), -1, cv2.LINE_AA)                             # stain
    save("fabric.jpg", cv2.GaussianBlur(img, (3, 3), 0))


def pcb():
    h, w = 700, 1000
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 95, 30)
    for _ in range(40):
        y = int(rng.uniform(20, h - 20))
        x1, x2 = sorted(rng.uniform(20, w - 20, 2).astype(int))
        cv2.line(img, (x1, y), (x2, y), (60, 160, 190), 4)
        x = int(rng.uniform(20, w - 20))
        y1, y2 = sorted(rng.uniform(20, h - 20, 2).astype(int))
        cv2.line(img, (x, y1), (x, y2), (60, 160, 190), 4)
    comps = [(120, 120, 140, 70), (350, 100, 90, 90), (600, 140, 180, 60), (180, 400, 60, 120), (420, 380, 120, 80),
             (700, 420, 90, 140), (850, 120, 70, 70), (520, 580, 160, 50)]
    for x, y, cw, ch in comps:
        cv2.rectangle(img, (x, y), (x + cw, y + ch), (30, 30, 30), -1)
        for k in range(0, cw, 18):
            cv2.rectangle(img, (x + k + 3, y - 8), (x + k + 11, y), (200, 200, 205), -1)
            cv2.rectangle(img, (x + k + 3, y + ch), (x + k + 11, y + ch + 8), (200, 200, 205), -1)
    ref = cv2.GaussianBlur(img, (3, 3), 0)
    test = img.copy()
    x, y, cw, ch = comps[3]
    test[y - 9:y + ch + 9, x - 2:x + cw + 2] = (40, 95, 30)              # missing component
    cv2.circle(test, (640, 260), 12, (210, 210, 215), -1, cv2.LINE_AA)   # solder blob
    test = cv2.GaussianBlur(test, (3, 3), 0)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 1.2, 1.0)
    M[0, 2] += 9
    M[1, 2] -= 6
    test = cv2.warpAffine(test, M, (w, h), borderValue=(40, 95, 30))
    save("pcb_reference.jpg", ref)
    save("pcb_test.jpg", test)


def thermal():
    h, w = 700, 1000
    t = np.full((h, w), 70, np.float32)
    for r in range(4):
        for c in range(6):
            x0, y0 = 60 + c * 150, 60 + r * 150
            t[y0:y0 + 135, x0:x0 + 135] = 110 + rng.normal(0, 4)
    t[60 + 150:60 + 150 + 135, 60 + 3 * 150:60 + 3 * 150 + 135] += 0
    cv2.circle(t, (60 + 3 * 150 + 70, 60 + 150 + 60), 30, 235, -1)
    t = cv2.GaussianBlur(t, (0, 0), 6) + rng.normal(0, 2, (h, w))
    save("thermal.jpg", cv2.applyColorMap(np.clip(t, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO))


def leaf():
    h, w = 800, 1000
    img = np.full((h, w, 3), 245, np.uint8)
    cv2.ellipse(img, (500, 400), (380, 210), -15, 0, 360, (40, 150, 60), -1, cv2.LINE_AA)
    cv2.line(img, (140, 500), (860, 300), (60, 180, 90), 6, cv2.LINE_AA)
    for _ in range(14):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, 1)
        cx = int(500 + 320 * r * math.cos(a))
        cy = int(400 + 160 * r * math.sin(a))
        rad = int(rng.uniform(10, 32))
        cv2.circle(img, (cx, cy), rad + 6, (60, 190, 210), -1, cv2.LINE_AA)  # yellow halo
        cv2.circle(img, (cx, cy), rad, (30, 70, 120), -1, cv2.LINE_AA)       # brown lesion
    save("leaf.jpg", cv2.GaussianBlur(img, (3, 3), 0))


def galaxy():
    S = 600
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) - S / 2
    r = np.sqrt(xx ** 2 + yy ** 2) + 1e-3
    th = np.arctan2(yy, xx)
    bulge = 255 * np.exp(-r / 22)
    arms = np.zeros_like(r)
    for k in range(2):
        phase = th - 0.42 * np.log(r) * 6 + k * math.pi
        arms += np.exp(-((np.sin(phase)) ** 2) / 0.06) * np.exp(-r / 120)
    img = bulge + 170 * arms + rng.normal(0, 4, r.shape)
    img = cv2.GaussianBlur(np.clip(img, 0, 255).astype(np.uint8), (0, 0), 2)
    col = cv2.merge([img, (img * 0.9).astype(np.uint8), (img * 0.8).astype(np.uint8)])
    for _ in range(40):
        cv2.circle(col, (int(rng.uniform(0, S)), int(rng.uniform(0, S))), 1, (255, 255, 255), -1)
    save("galaxy.jpg", col)


def coral():
    h, w = 700, 1000
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (120, 85, 20)
    img = (img * np.linspace(1.2, 0.6, h)[:, None, None]).astype(np.uint8)
    for _ in range(26):
        cx, cy = int(rng.uniform(60, w - 60)), int(rng.uniform(300, h - 30))
        bleached = rng.uniform() < 0.3
        color = (225, 228, 232) if bleached else tuple(int(v) for v in rng.choice([[90, 110, 230], [150, 90, 200], [80, 160, 220]]))
        for _ in range(8):
            ang = rng.uniform(-2.6, -0.5)
            ln = rng.uniform(40, 110)
            cv2.line(img, (cx, cy), (int(cx + ln * math.cos(ang)), int(cy + ln * math.sin(ang))), color, int(rng.uniform(8, 16)), cv2.LINE_AA)
    save("coral.jpg", cv2.GaussianBlur(img, (5, 5), 0))


def aerial():
    h, w = 900, 1200
    img = np.zeros((h, w, 3), np.uint8)
    pal = [(60, 140, 80), (40, 110, 60), (70, 160, 150), (90, 130, 170), (50, 120, 100), (80, 150, 120)]
    cells_ = 6
    for r in range(cells_):
        for c in range(cells_ + 2):
            x0, y0 = c * w // (cells_ + 2), r * h // cells_
            pts = np.array([[x0 + rng.integers(-15, 15), y0 + rng.integers(-15, 15)],
                            [x0 + w // (cells_ + 2) + rng.integers(-15, 15), y0 + rng.integers(-15, 15)],
                            [x0 + w // (cells_ + 2) + rng.integers(-15, 15), y0 + h // cells_ + rng.integers(-15, 15)],
                            [x0 + rng.integers(-15, 15), y0 + h // cells_ + rng.integers(-15, 15)]], np.int32)
            col = np.array(pal[rng.integers(0, len(pal))]) + rng.integers(-12, 12, 3)
            cv2.fillPoly(img, [pts], tuple(int(v) for v in col))
            for k in range(0, 160, 9):
                cv2.line(img, (pts[0][0], pts[0][1] + k), (pts[1][0], pts[1][1] + k), tuple(int(v * 0.92) for v in col), 1)
    cv2.ellipse(img, (900, 650), (170, 110), 10, 0, 360, (120, 70, 30), -1, cv2.LINE_AA)
    cv2.line(img, (0, 300), (w, 360), (150, 150, 150), 16)
    cv2.line(img, (420, 0), (470, h), (150, 150, 150), 14)
    for _ in range(18):
        x, y = int(rng.uniform(470, 760)), int(rng.uniform(380, 560))
        cv2.rectangle(img, (x, y), (x + int(rng.uniform(20, 38)), y + int(rng.uniform(18, 32))), (200, 200, 205), -1)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    save("aerial.jpg", np.clip(img.astype(np.int16) + rng.normal(0, 5, img.shape).astype(np.int16), 0, 255).astype(np.uint8))


def floorplan():
    h, w = 800, 1100
    img = np.full((h, w, 3), 255, np.uint8)
    T = 12
    cv2.rectangle(img, (60, 60), (1040, 740), (0, 0, 0), T)
    cv2.line(img, (520, 60), (520, 420), (0, 0, 0), T)
    cv2.line(img, (60, 420), (1040, 420), (0, 0, 0), T)
    cv2.line(img, (760, 420), (760, 740), (0, 0, 0), T)
    for x1, y1, x2, y2 in ((520, 250, 520, 330), (300, 420, 390, 420), (850, 420, 940, 420), (760, 560, 760, 640), (60, 560, 60, 640)):
        cv2.line(img, (x1, y1), (x2, y2), (255, 255, 255), T + 2)
    for (x, y), name in (((200, 240), "Living"), ((700, 240), "Kitchen"), ((330, 600), "Bedroom"), ((850, 600), "Bath")):
        cv2.putText(img, name, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (60, 60, 60), 2, cv2.LINE_AA)
    save("floorplan.jpg", img)


def measure():
    h, w = 800, 1200
    img = np.full((h, w, 3), 238, np.uint8)
    cv2.circle(img, (160, 400), 60, (60, 90, 160), -1, cv2.LINE_AA)  # reference: 2.5 cm coin
    cv2.rectangle(img, (420, 220), (760, 520), (90, 120, 60), -1)
    box = cv2.boxPoints(((980, 420), (200, 140), 25)).astype(np.int32)
    cv2.fillPoly(img, [box], (40, 60, 140))
    save("measure.jpg", cv2.GaussianBlur(img, (3, 3), 0))


def plate():
    bus = cv2.imread(str(OUT / "bus.jpg"))
    img = Image.new("RGB", (420, 150), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 419, 149], outline=(20, 20, 20), width=6)
    d.line([300, 6, 300, 144], fill=(20, 20, 20), width=4)
    d.line([6, 75, 300, 75], fill=(20, 20, 20), width=3)
    text(d, (150, 12), "١٢٣٤   ح ب ا", 44, rtl=False, anchor="ma")
    text(d, (150, 84), "1234   A B J", 44, anchor="ma", path=FONT_B)
    text(d, (360, 30), "KSA", 26, anchor="ma", path=FONT_B)
    p = to_cv(img)
    src = np.float32([[0, 0], [420, 0], [420, 150], [0, 150]])
    dst = np.float32([[330, 645], [540, 650], [538, 724], [330, 718]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(p, M, (bus.shape[1], bus.shape[0]))
    mask = cv2.warpPerspective(np.full((150, 420), 255, np.uint8), M, (bus.shape[1], bus.shape[0]))
    bus[mask > 0] = warped[mask > 0]
    save("plate.jpg", bus)
    save("plate_crop.jpg", p)


# ------------------------------------------------------------------ degraded photos, gallery, forgery, 3D

def degraded():
    bus = cv2.imread(str(OUT / "bus.jpg"))
    dark = np.clip(((bus / 255.0) ** 2.6) * 255 * 0.45 + rng.normal(0, 4, bus.shape), 0, 255).astype(np.uint8)
    save("lowlight.jpg", dark)
    k = np.zeros((21, 21), np.float32)
    k[10, :] = 1 / 21
    save("blurry.jpg", cv2.filter2D(bus, -1, k))
    small = cv2.resize(bus, (bus.shape[1] // 4, bus.shape[0] // 4), interpolation=cv2.INTER_AREA)
    save("lowres.jpg", small)
    g = cv2.cvtColor(bus, cv2.COLOR_BGR2GRAY)
    sep = cv2.merge([(g * 0.75).astype(np.uint8), (g * 0.88).astype(np.uint8), g])
    old = cv2.addWeighted(sep, 0.85, np.full_like(sep, (150, 180, 200)), 0.15, 0)
    for _ in range(14):
        x = int(rng.uniform(0, old.shape[1]))
        cv2.line(old, (x, 0), (x + int(rng.uniform(-60, 60)), old.shape[0]), (235, 240, 242), int(rng.uniform(1, 3)), cv2.LINE_AA)
    for _ in range(40):
        cv2.circle(old, (int(rng.uniform(0, old.shape[1])), int(rng.uniform(0, old.shape[0]))), int(rng.uniform(2, 6)), (230, 235, 238), -1)
    save("old_photo.jpg", old)
    save("grayscale.jpg", cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))


def gallery():
    gdir = OUT / "gallery"
    gdir.mkdir(exist_ok=True)
    bus = cv2.imread(str(OUT / "bus.jpg"))
    zid = cv2.imread(str(OUT / "zidane.jpg"))
    items = {
        "bus.jpg": bus, "bus_copy_small.jpg": cv2.resize(bus, (405, 540)),
        "bus_brighter.jpg": cv2.convertScaleAbs(bus, alpha=1.15, beta=20),
        "bus_cropped.jpg": bus[60:1000, 40:780], "zidane.jpg": zid, "zidane_flipped.jpg": cv2.flip(zid, 1),
        "street_people.jpg": bus[380:1000, 0:810], "leaf.jpg": cv2.imread(str(OUT / "leaf.jpg")),
        "aerial.jpg": cv2.imread(str(OUT / "aerial.jpg")), "pcb.jpg": cv2.imread(str(OUT / "pcb_reference.jpg")),
        "document.jpg": cv2.imread(str(OUT / "document.jpg")), "galaxy.jpg": cv2.imread(str(OUT / "galaxy.jpg")),
    }
    for k, v in items.items():
        cv2.imwrite(str(gdir / k), v, [cv2.IMWRITE_JPEG_QUALITY, 90])


def forgery():
    bus = cv2.imread(str(OUT / "bus.jpg"))
    fake = bus.copy()
    patch = bus[400:900, 50:240].copy()   # copy a person ...
    fake[420:920, 560:750] = patch          # ... and paste them elsewhere
    cv2.imwrite(str(OUT / "_tmp.jpg"), fake, [cv2.IMWRITE_JPEG_QUALITY, 75])
    f2 = cv2.imread(str(OUT / "_tmp.jpg"))
    (OUT / "_tmp.jpg").unlink()
    save("forgery.jpg", f2)


def stereo():
    """Three views of a box corner whose faces carry photo textures, for multi-view reconstruction."""
    tex = [cv2.imread(str(OUT / n)) for n in ("bus.jpg", "zidane.jpg", "document_flat.jpg")]
    planes = [  # 3D corners (x, y, z) of each textured face; camera looks down +z
        np.float32([[-2, -1.5, 8], [2, -1.5, 8], [2, 1.5, 8], [-2, 1.5, 8]]),        # back wall
        np.float32([[-2, -1.5, 4.5], [-2, -1.5, 8], [-2, 1.5, 8], [-2, 1.5, 4.5]]),  # left wall
        np.float32([[-2, 1.5, 8], [2, 1.5, 8], [2, 1.5, 4.5], [-2, 1.5, 4.5]]),       # floor
    ]
    K = np.array([[900, 0, 600], [0, 900, 400], [0, 0, 1]], np.float32)
    for k, (rvec, tvec) in enumerate((((0, 0, 0), (0, 0, 0)), ((0, -0.08, 0), (-0.55, 0, 0.05)), ((0, -0.16, 0), (-1.1, 0, 0.12)))):
        img = np.full((800, 1200, 3), 35, np.uint8)
        for pl, tx in sorted(zip(planes, tex), key=lambda pt: -pt[0][:, 2].mean()):
            proj, _ = cv2.projectPoints(pl, np.float32(rvec), np.float32(tvec), K, None)
            th, tw = tx.shape[:2]
            M = cv2.getPerspectiveTransform(np.float32([[0, 0], [tw, 0], [tw, th], [0, th]]), proj.reshape(4, 2).astype(np.float32))
            warped = cv2.warpPerspective(tx, M, (1200, 800))
            mask = cv2.warpPerspective(np.full((th, tw), 255, np.uint8), M, (1200, 800))
            img[mask > 0] = warped[mask > 0]
        save(f"view_{k + 1}.jpg", img)


def palm():
    for name, seed in (("palm_a.jpg", 3), ("palm_b.jpg", 3), ("palm_c.jpg", 11)):
        r = np.random.default_rng(seed)
        img = np.full((700, 600, 3), (150, 175, 215), np.uint8)
        cv2.ellipse(img, (300, 380), (210, 260), 0, 0, 360, (120, 150, 200), -1, cv2.LINE_AA)
        for _ in range(9):
            pts = np.cumsum(r.normal(0, 8, (40, 2)), axis=0) + [r.uniform(140, 420), r.uniform(200, 560)]
            cv2.polylines(img, [pts.astype(np.int32)], False, (70, 95, 140), int(r.uniform(2, 5)), cv2.LINE_AA)
        if name == "palm_b.jpg":
            M = cv2.getRotationMatrix2D((300, 350), 6, 1.03)
            img = cv2.warpAffine(img, M, (600, 700), borderValue=(150, 175, 215))
            img = cv2.convertScaleAbs(img, alpha=1.05, beta=6)
        save(name, cv2.GaussianBlur(img, (3, 3), 0))


def garment():
    img = np.full((600, 520, 3), 252, np.uint8)
    body = np.array([[130, 80], [200, 50], [320, 50], [390, 80], [500, 190], [430, 250], [390, 210], [390, 560], [130, 560],
                     [130, 210], [90, 250], [20, 190]], np.int32)
    cv2.fillPoly(img, [body], (60, 70, 200))
    cv2.ellipse(img, (260, 55), (60, 30), 0, 0, 180, (252, 252, 252), -1)
    cv2.putText(img, "ATLAS", (175, 330), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (250, 250, 250), 5, cv2.LINE_AA)
    save("garment.jpg", img)


def bottles():
    h, w = 700, 1200
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (228, 230, 232)
    img[560:] = (90, 95, 100)                                    # conveyor
    levels = [0.86, 0.58, 0.87, 1.0, 0.84]
    for i, lv in enumerate(levels):
        x0 = 110 + i * 210
        top, bottom, body_top = 140, 560, 240
        body = np.array([[x0, bottom], [x0, body_top], [x0 + 25, body_top - 40], [x0 + 45, top + 20], [x0 + 45, top],
                         [x0 + 95, top], [x0 + 95, top + 20], [x0 + 115, body_top - 40], [x0 + 140, body_top], [x0 + 140, bottom]], np.int32)
        glass = img.copy()
        cv2.fillPoly(glass, [body], (215, 225, 222))
        img = cv2.addWeighted(glass, 0.6, img, 0.4, 0)
        liquid_top = int(bottom - lv * (bottom - top))
        lm = np.zeros((h, w), np.uint8)
        cv2.fillPoly(lm, [body], 1)
        lm[:liquid_top] = 0
        img[lm > 0] = (30, 110, 175)
        cv2.polylines(img, [body], True, (120, 130, 130), 3, cv2.LINE_AA)
        if i != 2:                                               # bottle 3 has no cap
            cv2.rectangle(img, (x0 + 40, top - 30), (x0 + 100, top + 4), (40, 40, 190), -1)
    save("bottles.jpg", cv2.GaussianBlur(img, (3, 3), 0))


# ------------------------------------------------------------------ videos

def write_video(path, frames_iter, fps):
    import imageio_ffmpeg
    gen = None
    for f in frames_iter:
        if gen is None:
            h, w = f.shape[:2]
            gen = imageio_ffmpeg.write_frames(str(path), (w, h), fps=fps, codec="libx264", pix_fmt_in="bgr24",
                                              pix_fmt_out="yuv420p", quality=6, macro_block_size=2, ffmpeg_log_level="error")
            gen.send(None)
        gen.send(np.ascontiguousarray(f))
    gen.close()


def street_video():
    bus = cv2.imread(str(OUT / "bus.jpg"))
    wide = cv2.hconcat([bus, cv2.flip(bus, 1)])
    W = 640
    wide = cv2.resize(wide, (int(wide.shape[1] * 640 / bus.shape[0] * 0.75), 480))
    n = 75
    span = wide.shape[1] - W

    def gen():
        for i in range(n):
            x = int(span * i / (n - 1))
            yield wide[:, x:x + W]
    write_video(OUT / "street.mp4", gen(), 15)


def fall_video():
    zid = cv2.imread(str(OUT / "zidane.jpg"))
    h, w = zid.shape[:2]
    person = cv2.resize(zid[:, 640:], (360, 405))
    canvas_h, canvas_w = 480, 640

    def gen():
        for i in range(70):
            ang = 0 if i < 20 else min(85, (i - 20) * 9)
            frame = np.full((canvas_h, canvas_w, 3), 200, np.uint8)
            M = cv2.getRotationMatrix2D((180, 400), -ang, 1.0)
            rot = cv2.warpAffine(person, M, (canvas_w, canvas_h), borderValue=(200, 200, 200))
            frame = rot
            yield frame
    write_video(OUT / "fall.mp4", gen(), 15)


def posters():
    """First frame of each sample video, used by the lab to draw lines and zones before upload."""
    for v in OUT.glob("*.mp4"):
        cap = cv2.VideoCapture(str(v))
        ok, frame = cap.read()
        cap.release()
        if ok:
            save(f"{v.stem}.poster.jpg", frame)


def main():
    OUT.mkdir(exist_ok=True)
    for fn in (document, receipt, id_card, whiteboard, table_doc, math_img, qr_codes, omr, gauge, crack, particles, cells,
               fabric, pcb, thermal, leaf, galaxy, coral, aerial, floorplan, measure, plate, degraded, gallery, forgery,
               stereo, palm, garment, bottles, street_video, fall_video, posters):
        fn()
        print("made", fn.__name__)


if __name__ == "__main__":
    main()
