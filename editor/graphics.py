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
        d.rounded_rectangle([cxm - 640, H - 250, cxm + 640, H - 180], 10, fill=(0, 0, 0, int(170 * k)))
        d.text((cxm, H - 215), caption, font=font(SANS, 34, 700), fill=WHITE + (int(255 * k),), anchor="mm")
    return img.convert("RGB")


if __name__ == "__main__":
    out = os.path.join(ROOT, "work")
    chart_frame(1.0, "peak").save(f"{out}/g_chart_peak.jpg", quality=90)
    chart_frame(0.85, "crash").save(f"{out}/g_chart_crash.jpg", quality=90)
    map_frame(0.95).save(f"{out}/g_map.jpg", quality=90)
