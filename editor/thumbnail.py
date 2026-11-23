"""Firmenfriedhof thumbnails in the RealLifeLore style.

Bright, punchy background; the subject (nearest object, found by depth) picked out in red with a white
outline; a thick white curved arrow pointing at it; 2-4 words in heavy white capitals on black boxes with
one accent word in red or yellow (underlined); optional photo "card" with a white border.

Normally the background is a dedicated Flow image whose prompt already asks for the red highlight and the
white arrow (Nano Banana draws those well); this script adds the text boxes, badge and photo card.
spec = {"bg": path, "lines": ["1,9 MRD. €", "EINFACH WEG"], "accent": "WEG", "accent_color": "red",
        "subject": "red" | "outline" | "none", "arrow": true, "inset": path or None,
        "badge": "SKANDAL" or None, "text_pos": "bottom_left" | "top_left"}
Usage: python3 editor/thumbnail.py spec.json out.jpg
"""
import json, math, os, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

TW, TH = 1280, 720
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), "assets", "fonts")
HEAVY = os.path.join(FONTS, "Montserrat[wght].ttf")
RED, YELLOW, WHITE, BLACK = (232, 30, 36), (255, 214, 0), (255, 255, 255), (0, 0, 0)


def heavy(size):
    f = ImageFont.truetype(HEAVY, size)
    try:
        f.set_variation_by_axes([900])
    except Exception:
        pass
    return f


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def punch(im):
    im = ImageEnhance.Color(im).enhance(1.35)
    im = ImageEnhance.Contrast(im).enhance(1.18)
    im = ImageEnhance.Brightness(im).enhance(1.08)
    return im.filter(ImageFilter.UnsharpMask(2, 90, 2))


def subject_mask(path, size, focus):
    """Mask of the object inside `focus` [x0,y0,x1,y1] (0..1) that stands out in front, from the depth model."""
    sys.path.insert(0, HERE)
    from make_video_v3 import depth_map
    d = depth_map(path, size)
    W_, H_ = size
    x0, y0, x1, y1 = int(focus[0] * W_), int(focus[1] * H_), int(focus[2] * W_), int(focus[3] * H_)
    box = d[y0:y1, x0:x1]
    full = (d >= np.percentile(box, 60)).astype(np.uint8)  # natural shape, not clipped to the box
    n, lab, stats, _ = cv2.connectedComponentsWithStats(full, 8)
    inside = np.bincount(lab[y0:y1, x0:x1].ravel(), minlength=n)
    inside[0] = 0
    m = (lab == int(np.argmax(inside))).astype(np.uint8)
    m[: max(0, y0 - (y1 - y0) // 3)] = 0  # keep it near the box
    m[min(H_, y1 + (y1 - y0) // 3):] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    return m


def draw_arrow(img, start, end, width=22):
    """Thick white curved arrow with a dark shadow."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    (x0, y0), (x1, y1) = start, end
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    nx, ny = -(y1 - y0), (x1 - x0)
    L = math.hypot(nx, ny) or 1
    c = (mx + nx / L * 0.28 * math.hypot(x1 - x0, y1 - y0), my + ny / L * 0.28 * math.hypot(x1 - x0, y1 - y0))
    pts = []
    for i in range(41):
        t = i / 40 * 0.86  # stop before the tip; the head covers the rest
        pts.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * c[0] + t ** 2 * x1,
                    (1 - t) ** 2 * y0 + 2 * (1 - t) * t * c[1] + t ** 2 * y1))
    tx, ty = pts[-1]
    ang = math.atan2(y1 - ty, x1 - tx)
    head = width * 2.6
    tip = (x1, y1)
    left = (tx + math.cos(ang + 2.3) * head * 0.55, ty + math.sin(ang + 2.3) * head * 0.55)
    right = (tx + math.cos(ang - 2.3) * head * 0.55, ty + math.sin(ang - 2.3) * head * 0.55)
    for col, off, w in ((BLACK + (150,), 6, width + 6), (WHITE + (255,), 0, width)):
        p2 = [(x + off, y + off) for x, y in pts]
        d.line(p2, fill=col, width=w, joint="curve")
        d.ellipse([p2[0][0] - w / 2, p2[0][1] - w / 2, p2[0][0] + w / 2, p2[0][1] + w / 2], fill=col)
        d.polygon([(tip[0] + off, tip[1] + off), (left[0] + off, left[1] + off), (right[0] + off, right[1] + off)], fill=col)
    shadow = layer.filter(ImageFilter.GaussianBlur(1))
    img.alpha_composite(shadow)


def text_boxes(img, lines, accent, accent_color, pos):
    d = ImageDraw.Draw(img)
    size = 92 if max(len(l) for l in lines) <= 12 else 74
    f = heavy(size)
    pad_x, pad_y, gap = 22, 12, -6
    heights = [f.getbbox(l.upper())[3] - f.getbbox(l.upper())[1] for l in lines]
    total = sum(h + 2 * pad_y for h in heights) + gap * (len(lines) - 1)
    x = 42
    y = TH - total - 46 if pos == "bottom_left" else 46
    acc = (YELLOW if accent_color == "yellow" else RED)
    for line, h in zip(lines, heights):
        words = line.upper().split(" ")
        widths = [f.getlength(w) for w in words]
        space = f.getlength(" ")
        w_total = sum(widths) + space * (len(words) - 1)
        d.rectangle([x, y, x + w_total + 2 * pad_x, y + h + 2 * pad_y], fill=BLACK)
        cx = x + pad_x
        top = y + pad_y - f.getbbox(line.upper())[1]
        for wd, ww in zip(words, widths):
            is_acc = bool(accent) and wd.strip(",.!?") in [a.strip(",.!?") for a in accent.upper().split()]
            d.text((cx, top), wd, font=f, fill=acc if is_acc else WHITE)
            if is_acc and accent_color == "yellow":
                d.rectangle([cx, y + h + pad_y + 4, cx + ww, y + h + pad_y + 10], fill=acc)
            cx += ww + space
        y += h + 2 * pad_y + gap


def inset_card(img, path, box, angle=-6):
    """Photo with a thick white border, slightly rotated, with a drop shadow."""
    x, y, w, h = box
    ph = cover(punch(Image.open(path).convert("RGB")), w, h)
    border = 12
    card = Image.new("RGBA", (w + 2 * border, h + 2 * border), WHITE + (255,))
    card.paste(ph, (border, border))
    card = card.rotate(angle, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    sh.putalpha(card.split()[3].point(lambda v: int(v * 0.55)))
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(sh, (x + 10, y + 12))
    img.alpha_composite(card, (x, y))


def make(spec, out):
    bg = Image.open(spec["bg"]).convert("RGB")
    bg = bg.crop((0, 0, int(bg.width * 0.93), int(bg.height * 0.93)))  # drop Flow's corner mark
    tmp = os.path.join(os.path.dirname(os.path.abspath(out)), "_thumb_bg.png")
    cover(bg, TW, TH).save(tmp)
    base = punch(Image.open(tmp).convert("RGB")).convert("RGBA")
    # light vignette so text and arrow pop
    yy, xx = np.mgrid[0:TH, 0:TW]
    dd = np.sqrt(((xx - TW / 2) / TW) ** 2 + ((yy - TH / 2) / TH) ** 2)
    v = np.clip(1.1 - 0.5 * dd ** 1.6, 0.6, 1)[..., None]
    arr = np.asarray(base).astype(np.float32)
    arr[..., :3] *= v
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")

    target = None
    mode = spec.get("subject", "none")  # default: Nano Banana already drew highlight + arrow into the image
    if mode != "none" and spec.get("focus"):
        m = subject_mask(tmp, (TW, TH), spec["focus"])
        if m.sum() > 2000:
            ys, xs = np.nonzero(m)
            target = (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))
            a = np.asarray(img).astype(np.float32)
            if mode == "red":
                tint = np.array([RED[0], RED[1], RED[2]], np.float32)
                lum = a[..., :3].mean(axis=2, keepdims=True)
                red = np.clip(lum * 0.35 + tint * 0.75, 0, 255)
                k = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.5)[..., None] * 0.78
                a[..., :3] = a[..., :3] * (1 - k) + red * k
            edge = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, np.ones((7, 7), np.uint8)).astype(bool)
            a[edge, :3] = 255
            img = Image.fromarray(a.clip(0, 255).astype(np.uint8), "RGBA")

    if spec.get("inset"):
        bx = TW - 430 if spec.get("text_pos", "bottom_left") == "bottom_left" else 60
        inset_card(img, spec["inset"], (bx, 70, 340, 250), angle=6 if bx > TW / 2 else -6)

    if spec.get("arrow", False) and target:
        bx0, bx1, by0, by1 = target
        cy = by0 + (by1 - by0) * 0.45
        if (bx0 + bx1) / 2 > TW / 2:  # subject on the right: arrow comes from the left
            end = (max(bx0 - 14, 60), cy)
            start = (max(end[0] - 260, 40), min(cy + 170, TH - 250))
        else:
            end = (min(bx1 + 14, TW - 60), cy)
            start = (min(end[0] + 260, TW - 40), min(cy + 170, TH - 250))
        if abs(start[0] - end[0]) > 80:
            draw_arrow(img, start, end)

    if spec.get("badge"):
        d = ImageDraw.Draw(img)
        f = heavy(40)
        t = spec["badge"].upper()
        w = f.getlength(t)
        d.rectangle([42, 40, 42 + w + 32, 104], fill=BLACK)
        d.text((58, 72), t, font=f, fill=WHITE, anchor="lm")

    text_boxes(img, spec["lines"], spec.get("accent"), spec.get("accent_color", "red"),
               spec.get("text_pos", "bottom_left"))
    img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    os.remove(tmp)
    return out


if __name__ == "__main__":
    make(json.load(open(sys.argv[1])), sys.argv[2])
