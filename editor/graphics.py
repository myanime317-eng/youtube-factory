"""Motion graphics for Firmenfriedhof: animated stock chart and route map.

Every function returns a 1920x1080 RGB PIL image for a progress value p in 0..1.
"""
import json, math, os
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
SERIF = os.path.join(FONTS, "Cardo-Bold.ttf")
SANS = os.path.join(FONTS, "Montserrat[wght].ttf")
GOLD, WHITE, RED, NAVY = (214, 178, 92), (238, 236, 230), (214, 52, 44), (10, 16, 28)
GREY = (120, 130, 148)


def font(path, size, weight=None):
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


@lru_cache(maxsize=4)
def _bg(seed=0):
    """Dark navy backdrop with a soft spotlight and faint noise texture."""
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W * 0.5) / W) ** 2 + ((yy - H * 0.45) / H) ** 2)
    base = np.array(NAVY, np.float32) * (1.35 - 0.9 * d)[..., None]
    rng = np.random.default_rng(seed)
    base += rng.normal(0, 1.2, (H, W, 1))
    return Image.fromarray(base.clip(0, 255).astype(np.uint8))


def glow(layer, radius=10, strength=1.0):
    """Adds a soft glow under an RGBA layer."""
    g = layer.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        a = np.asarray(g).astype(np.float32)
        a[..., 3] *= strength
        g = Image.fromarray(a.clip(0, 255).astype(np.uint8))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(g)
    out.alpha_composite(layer)
    return out


# ------------------------------------------------------------------ stock chart
# Wirecard share price (EUR), approximate monthly closes; key points are real:
# ~191 at the Sept 2018 peak, ~104 on 17 June 2020, ~1.3 a week later.
PRICE = [
    ("2014", 31), ("", 33), ("", 36), ("2015", 39), ("", 42), ("", 40), ("2016", 37), ("", 41), ("", 44),
    ("2017", 50), ("", 66), ("", 85), ("2018", 105), ("", 140), ("", 172), ("SEP 2018", 191), ("", 160),
    ("2019", 135), ("", 145), ("", 140), ("", 120), ("2020", 115), ("", 100), ("", 104), ("JUN 2020", 1.3),
]


def chart_frame(p, upto="peak", label="Aktienkurs Wirecard (EUR)"):
    """upto='peak': draws 2014 -> Sept 2018 (rise). upto='crash': shows the whole line and plays the crash."""
    peak_i = 15
    pts = PRICE
    x0, x1, y0, y1 = 210, W - 210, (400 if upto == "peak" else 250), H - 230
    vmax = 210.0

    def xy(i, v):
        return x0 + (x1 - x0) * i / (len(pts) - 1), y1 - (y1 - y0) * v / vmax

    img = _bg(1).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    # grid
    for v in (50, 100, 150, 200):
        y = xy(0, v)[1]
        d.line([(x0, y), (x1, y)], fill=(255, 255, 255, 18), width=1)
        d.text((x0 - 20, y), f"{v} €", font=font(SANS, 24, 500), fill=GREY + (160,), anchor="rm")
    for i, (lab, _) in enumerate(pts):
        if lab and not lab.startswith(("SEP", "JUN")):
            x = xy(i, 0)[0]
            d.text((x, y1 + 36), lab, font=font(SANS, 26, 600), fill=GREY + (200,), anchor="mm")
    d.text((x0, y0 - 70), label.upper(), font=font(SANS, 28, 700), fill=GREY + (220,), anchor="lm")

    if upto == "peak":
        end = ease_out(p) * peak_i
        start_crash = None
    else:
        end = peak_i + ease(min(1, p / 0.12)) * (len(pts) - 2 - peak_i)  # quick slide to June 2020
        start_crash = max(0.0, (p - 0.14) / 0.16)  # then the crash, right on the word
        if start_crash > 0:
            end = len(pts) - 2 + min(1.0, start_crash)

    line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    n = int(math.floor(end))
    poly = [xy(i, pts[i][1]) for i in range(n + 1)]
    if end > n and n + 1 < len(pts):
        f = end - n
        a, b = xy(n, pts[n][1]), xy(n + 1, pts[n + 1][1])
        poly.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    crashing = upto == "crash" and end > len(pts) - 2
    col = RED if crashing else GOLD
    if len(poly) > 1:
        area = poly + [(poly[-1][0], y1), (poly[0][0], y1)]
        ld.polygon(area, fill=col + (26,))
        ld.line(poly, fill=col + (255,), width=6, joint="curve")
        hx, hy = poly[-1]
        ld.ellipse([hx - 11, hy - 11, hx + 11, hy + 11], fill=WHITE + (255,))
        ld.ellipse([hx - 7, hy - 7, hx + 7, hy + 7], fill=col + (255,))
    line = glow(line, 14, 0.9)
    img.alpha_composite(line)

    d = ImageDraw.Draw(img)
    if len(poly) > 1:
        hx, hy = poly[-1]
        i_now = min(len(pts) - 1, int(round(end)))
        val = pts[min(n + 1, len(pts) - 1)][1] if crashing else None
        price = (pts[n][1] + (pts[min(n + 1, len(pts) - 1)][1] - pts[n][1]) * (end - n))
        tag = f"{price:,.1f} €".replace(".", ",") if price < 10 else f"{price:,.0f} €"
        tx, ty = min(hx + 30, x1 - 10), max(hy - 40, y0)
        d.rounded_rectangle([tx - 4, ty - 26, tx + 150, ty + 26], 8, fill=(0, 0, 0, 160))
        d.text((tx + 73, ty), tag, font=font(SANS, 30, 800), fill=col + (255,), anchor="mm")
        if upto == "peak" and end >= peak_i - 0.05:
            px, py = xy(peak_i, pts[peak_i][1])
            a = int(255 * min(1, (end - peak_i + 0.05) / 0.05))
            d.text((px - 30, py - 30), "SEP 2018", font=font(SANS, 26, 700), fill=GOLD + (a,), anchor="rm")
        if crashing:
            a = int(255 * min(1, start_crash * 2))
            d.text((xy(len(pts) - 1, 0)[0] - 10, y1 + 36), "JUN 2020", font=font(SANS, 26, 700),
                   fill=RED + (a,), anchor="rm")
            d.text((x1 - 40, y0 + 40), "−99 %", font=font(SERIF, 150), fill=RED + (a,), anchor="rm")
    return img.convert("RGB")


# ------------------------------------------------------------------ route map
@lru_cache(maxsize=1)
def _countries():
    with open(os.path.join(ROOT, "assets", "maps", "countries.json")) as f:
        return json.load(f)["features"]


def _proj(lon, lat, view):
    lon0, lon1, lat0, lat1 = view
    # equirectangular with cos(lat) correction around the view's middle latitude
    k = math.cos(math.radians((lat0 + lat1) / 2))
    x = (lon - lon0) / (lon1 - lon0)
    y = (lat1 - lat) / (lat1 - lat0)
    return x, y


@lru_cache(maxsize=4)
def _map_base(view, highlight, scale=1.3):
    """Draws the map once at `scale` x frame size."""
    mw, mh = int(W * scale), int(H * scale)
    img = _bg(2).resize((mw, mh)).convert("RGBA")
    land = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    d = ImageDraw.Draw(land)
    for f in _countries():
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        hl = f["properties"]["a3"] in highlight
        for poly in polys:
            ring = [(_proj(lo, la, view)) for lo, la in poly[0]]
            ring = [(x * mw, y * mh) for x, y in ring]
            if len(ring) < 3:
                continue
            fill = (60, 50, 30, 255) if hl else (28, 38, 56, 255)
            line = GOLD + (230,) if hl else (70, 86, 110, 200)
            d.polygon(ring, fill=fill, outline=line)
    img.alpha_composite(glow(land, 6, 0.6))
    return img


def map_frame(p, view=(-14.0, 140.0, -10.0, 64.0), a=(11.58, 48.14, "MÜNCHEN"), b=(120.98, 14.60, "MANILA"),
              highlight=("DEU", "PHL"), caption="1,9 MRD. € – angeblich auf Treuhandkonten auf den Philippinen"):
    scale = 1.3
    base = _map_base(view, highlight, scale)
    mw, mh = base.size
    # slow camera push toward the route's middle
    z = 1.0 + 0.05 * ease(p)
    ax, ay = _proj(a[0], a[1], view)
    bx, by = _proj(b[0], b[1], view)
    cx, cy = (ax + bx) / 2 * mw, (ay + by) / 2 * mh
    cw, ch = mw / z, mh / z
    left = min(max(cx - cw / 2, 0), mw - cw)
    top = min(max(cy - ch / 2, 0), mh - ch)
    img = base.transform((W, H), Image.EXTENT, (left, top, left + cw, top + ch), Image.BICUBIC)

    def to_screen(x, y):
        return ((x * mw - left) / cw * W, (y * mh - top) / ch * H)

    A, B = to_screen(ax, ay), to_screen(bx, by)
    mid = ((A[0] + B[0]) / 2, min(A[1], B[1]) - 260)
    t_line = ease(min(1, max(0, (p - 0.12) / 0.5)))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = []
    for i in range(0, 101):
        t = i / 100 * t_line
        x = (1 - t) ** 2 * A[0] + 2 * (1 - t) * t * mid[0] + t ** 2 * B[0]
        y = (1 - t) ** 2 * A[1] + 2 * (1 - t) * t * mid[1] + t ** 2 * B[1]
        pts.append((x, y))
    if t_line > 0:
        d.line(pts, fill=GOLD + (255,), width=5, joint="curve")
    for (P, name, show) in ((A, a[2], 0.0), (B, b[2], 0.62)):
        k = ease(min(1, max(0, (p - show) / 0.12)))
        if k <= 0:
            continue
        pulse = 1 + 0.35 * (0.5 + 0.5 * math.sin(p * 30))
        r = 12 * k
        d.ellipse([P[0] - r * 2.2 * pulse, P[1] - r * 2.2 * pulse, P[0] + r * 2.2 * pulse, P[1] + r * 2.2 * pulse],
                  outline=GOLD + (int(120 * k),), width=3)
        d.ellipse([P[0] - r, P[1] - r, P[0] + r, P[1] + r], fill=WHITE + (int(255 * k),))
        d.text((min(max(P[0], 140), W - 140), P[1] + 46), name, font=font(SANS, 34, 800), fill=WHITE + (int(255 * k),), anchor="mm")
    layer = glow(layer, 10, 0.9)
    img = img.convert("RGBA")
    img.alpha_composite(layer)
    k = ease(min(1, max(0, (p - 0.7) / 0.15)))
    if caption and k > 0:
        d = ImageDraw.Draw(img)
        cxm = W / 2 - 170
        half = font(SANS, 34, 700).getlength(caption) / 2 + 40
        d.rounded_rectangle([cxm - half, H - 250, cxm + half, H - 180], 10, fill=(0, 0, 0, int(170 * k)))
        d.text((cxm, H - 215), caption, font=font(SANS, 34, 700), fill=WHITE + (int(255 * k),), anchor="mm")
    return img.convert("RGB")


if __name__ == "__main__":
    out = os.path.join(ROOT, "work")
    chart_frame(1.0, "peak").save(f"{out}/g_chart_peak.jpg", quality=90)
    chart_frame(0.85, "crash").save(f"{out}/g_chart_crash.jpg", quality=90)
    map_frame(0.95).save(f"{out}/g_map.jpg", quality=90)


# ------------------------------------------------------------------ generic graphics (driven by the script)
def chart_spec_frame(p, g):
    """g: {"points": [[label, value], ...], "label": str, "unit": "€", "mode": "rise"|"crash"|"full",
           "peak": index (optional), "peak_label": str, "drop_label": "−99 %"}"""
    global PRICE
    old = PRICE
    try:
        PRICE = [(str(a), float(b)) for a, b in g["points"]]
        n = len(PRICE)
        vmax = max(v for _, v in PRICE) * 1.1
        peak_i = g.get("peak", max(range(n), key=lambda i: PRICE[i][1]))
        return _chart_generic(p, g.get("mode", "full"), g.get("label", ""), g.get("unit", "€"), vmax, peak_i,
                              g.get("peak_label", ""), g.get("drop_label", ""))
    finally:
        PRICE = old


def _chart_generic(p, mode, label, unit, vmax, peak_i, peak_label, drop_label):
    pts = PRICE
    x0, x1, y0, y1 = 210, W - 210, 300, H - 230

    def xy(i, v):
        return x0 + (x1 - x0) * i / (len(pts) - 1), y1 - (y1 - y0) * v / vmax

    img = _bg(1).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    raw = vmax / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    v = step
    while v < vmax:
        y = xy(0, v)[1]
        d.line([(x0, y), (x1, y)], fill=(255, 255, 255, 18), width=1)
        d.text((x0 - 20, y), f"{v:g} {unit}", font=font(SANS, 24, 500), fill=GREY + (160,), anchor="rm")
        v += step
    every = max(1, len(pts) // 8)
    for i, (lab, _) in enumerate(pts):
        if lab and i % every == 0:
            d.text((xy(i, 0)[0], y1 + 36), lab, font=font(SANS, 26, 600), fill=GREY + (200,), anchor="mm")
    d.text((x0, y0 - 70), label.upper(), font=font(SANS, 28, 700), fill=GREY + (220,), anchor="lm")
    last = len(pts) - 1
    if mode == "rise":
        end = ease_out(p) * peak_i
    elif mode == "crash":
        end = peak_i + ease(min(1, p / 0.6)) * (last - peak_i)
    else:
        end = ease_out(p) * last
    crashing = mode == "crash" or (end > peak_i and pts[last][1] < pts[peak_i][1] * 0.5)
    line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    n = int(math.floor(end))
    poly = [xy(i, pts[i][1]) for i in range(n + 1)]
    if end > n and n + 1 < len(pts):
        f = end - n
        a, b = xy(n, pts[n][1]), xy(n + 1, pts[n + 1][1])
        poly.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    col = RED if crashing and end > peak_i + 0.5 else GOLD
    if len(poly) > 1:
        ld.polygon(poly + [(poly[-1][0], y1), (poly[0][0], y1)], fill=col + (26,))
        ld.line(poly, fill=col + (255,), width=6, joint="curve")
        hx, hy = poly[-1]
        ld.ellipse([hx - 11, hy - 11, hx + 11, hy + 11], fill=WHITE + (255,))
        ld.ellipse([hx - 7, hy - 7, hx + 7, hy + 7], fill=col + (255,))
    img.alpha_composite(glow(line, 14, 0.9))
    d = ImageDraw.Draw(img)
    if len(poly) > 1:
        hx, hy = poly[-1]
        val = pts[n][1] + (pts[min(n + 1, last)][1] - pts[n][1]) * (end - n)
        tag = (f"{val:,.1f}" if val < 10 else f"{val:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".") + f" {unit}"
        tx, ty = min(hx + 30, x1 - 160), max(hy - 40, y0)
        d.rounded_rectangle([tx - 4, ty - 26, tx + 170, ty + 26], 8, fill=(0, 0, 0, 160))
        d.text((tx + 83, ty), tag, font=font(SANS, 30, 800), fill=col + (255,), anchor="mm")
        if peak_label and end >= peak_i - 0.05:
            px, py = xy(peak_i, pts[peak_i][1])
            d.text((px - 30, py - 30), peak_label, font=font(SANS, 26, 700), fill=GOLD + (255,), anchor="rm")
        if drop_label and mode == "crash" and p > 0.6:
            a = int(255 * min(1, (p - 0.6) / 0.15))
            d.text((x1 - 40, y0 + 40), drop_label, font=font(SERIF, 150), fill=RED + (a,), anchor="rm")
    return img.convert("RGB")


def map_spec_frame(p, g):
    """g: {"from": [lon, lat, "NAME"], "to": [lon, lat, "NAME"], "highlight": ["DEU"], "caption": str,
           "view": [lon0, lon1, lat0, lat1] optional}"""
    a, b = g["from"], g.get("to") or g["from"]
    view = g.get("view")
    if not view:
        lo0, lo1 = min(a[0], b[0]), max(a[0], b[0])
        la0, la1 = min(a[1], b[1]), max(a[1], b[1])
        span_lat = max((la1 - la0) * 1.6 + 14, 14)
        k = math.cos(math.radians((la0 + la1) / 2))
        span_lon = max((lo1 - lo0) * 1.35 + 16, span_lat * (W / H) / max(k, 0.3))
        cx, cy = (lo0 + lo1) / 2, (la0 + la1) / 2
        view = (cx - span_lon / 2, cx + span_lon / 2, cy - span_lat / 2, cy + span_lat / 2)
    return map_frame(p, tuple(view), tuple(a), tuple(b), tuple(g.get("highlight", ())), g.get("caption", ""))


def timeline_frame(p, g):
    """g: {"events": [["2002", "Braun wird Chef"], ...], "focus": index to highlight}"""
    ev = g["events"]
    img = _bg(3).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    x0, x1, y = 180, W - 180, H / 2 + 20
    grow = ease_out(min(1, p / 0.5))
    d.line([(x0, y), (x0 + (x1 - x0) * grow, y)], fill=GREY + (200,), width=4)
    focus = g.get("focus", len(ev) - 1)
    for i, (yr, txt) in enumerate(ev):
        x = x0 + (x1 - x0) * (i / max(1, len(ev) - 1))
        k = ease(min(1, max(0, (p * 1.6 - i / max(1, len(ev)) * 0.8) / 0.25)))
        if k <= 0:
            continue
        hot = i == focus
        col = (RED if g.get("focus_red") else GOLD) if hot else WHITE
        r = 14 if hot else 9
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (int(255 * k),))
        up = i % 2 == 0
        d.text((x, y - 60 if up else y + 60), yr, font=font(SANS, 40 if hot else 32, 800), fill=col + (int(255 * k),), anchor="mm")
        lines = _wrap(txt, 18)
        for j, l in enumerate(lines):
            yy = (y - 110 - (len(lines) - 1 - j) * 36) if up else (y + 108 + j * 36)
            d.text((x, yy), l, font=font(SANS, 28, 600), fill=(WHITE if hot else GREY) + (int(255 * k),), anchor="mm")
    return img.convert("RGB")


def _wrap(t, n):
    words, lines, cur = t.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def quote_frame(p, g):
    """g: {"text": "...", "by": "Name, Rolle"}"""
    img = _bg(4).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    k = ease(min(1, p / 0.2))
    d.text((W / 2, 250), "„", font=font(SERIF, 260), fill=GOLD + (int(200 * k),), anchor="mm")
    lines = _wrap(g["text"], 34)
    shown = int(len(" ".join(lines)) * min(1, p / 0.6))
    y = H / 2 - (len(lines) - 1) * 38
    used = 0
    for l in lines:
        part = l[: max(0, shown - used)]
        used += len(l) + 1
        d.text((W / 2, y), part, font=font(SERIF, 64), fill=WHITE + (255,), anchor="mm")
        y += 76
    if g.get("by"):
        a = int(255 * ease(min(1, max(0, (p - 0.55) / 0.2))))
        d.line([(W / 2 - 60, y + 24), (W / 2 + 60, y + 24)], fill=GOLD + (a,), width=3)
        d.text((W / 2, y + 70), g["by"].upper(), font=font(SANS, 30, 700), fill=GREY + (a,), anchor="mm")
    return img.convert("RGB")


def card_frame(p, g):
    """Person card with a silhouette (never a real face). g: {"name", "role", "note", "status": "red"|"gold"}"""
    img = _bg(5).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    col = RED if g.get("status") == "red" else GOLD
    k = ease_out(min(1, p / 0.25))
    cx, cy = W / 2 - 330 + (1 - k) * -80, H / 2
    # silhouette: head + shoulders
    sil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    sd.ellipse([cx - 85, cy - 210, cx + 85, cy - 30], fill=(40, 50, 68, 255))
    sd.rounded_rectangle([cx - 175, cy - 20, cx + 175, cy + 216], 110, fill=(40, 50, 68, 255))
    sd.rectangle([cx - 230, cy - 260, cx + 230, cy + 220], outline=col + (255,), width=5)
    img.alpha_composite(sil)
    d.text((cx, cy - 115), "?", font=font(SERIF, 120), fill=(90, 104, 128, 255), anchor="mm")
    a = int(255 * ease(min(1, max(0, (p - 0.1) / 0.2))))
    tx = W / 2 - 40
    d.text((tx, cy - 90), g["name"].upper(), font=font(SANS, 72, 900), fill=WHITE + (a,), anchor="lm")
    d.text((tx, cy - 10), g.get("role", ""), font=font(SANS, 36, 600), fill=col + (a,), anchor="lm")
    if g.get("note"):
        a2 = int(255 * ease(min(1, max(0, (p - 0.35) / 0.2))))
        for j, l in enumerate(_wrap(g["note"], 34)):
            d.text((tx, cy + 70 + j * 46), l, font=font(SANS, 34, 500), fill=GREY + (a2,), anchor="lm")
    return img.convert("RGB")


def text_frame(p, g):
    """Statement card: g: {"title": "...", "sub": "..."}"""
    img = _bg(6).copy().convert("RGBA")
    d = ImageDraw.Draw(img)
    k = ease(min(1, p / 0.2))
    sc = 1.04 - 0.04 * k
    d.text((W / 2, H / 2 - 30), g["title"], font=font(SERIF, int(110 * sc)), fill=(RED if g.get("red") else WHITE) + (int(255 * k),), anchor="mm")
    if g.get("sub"):
        a = int(255 * ease(min(1, max(0, (p - 0.25) / 0.2))))
        d.text((W / 2, H / 2 + 70), g["sub"], font=font(SANS, 38, 600), fill=GREY + (a,), anchor="mm")
    return img.convert("RGB")


GRAPHICS = {"chart": chart_spec_frame, "map": map_spec_frame, "timeline": timeline_frame,
            "quote": quote_frame, "card": card_frame, "text": text_frame}
