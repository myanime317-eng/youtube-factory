"""Firmenfriedhof test editor: builds a Magnates-style cold open from
images + narration (with ElevenLabs character timings).

Usage: python3 editor/make_test_video.py <images_dir> <voice.mp3> <alignment.json> <out.mp4>
"""
import json, math, os, subprocess, sys, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS, SR = 1920, 1080, 30, 48000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
SERIF = os.path.join(FONTS, "Cardo-Bold.ttf")
SANS = os.path.join(FONTS, "Montserrat[wght].ttf")
GOLD, WHITE, RED, NAVY = (214, 178, 92), (238, 236, 230), (214, 52, 44), (12, 20, 34)
BAR = 131  # 2.35:1 letterbox

LEAD_IN = 1.2         # drone before the first word
PAUSE_BEFORE = 1.0    # silence inserted before "Einfach weg."
TITLE_LEN, CHAPTER_LEN = 4.0, 2.6


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


# ---------------------------------------------------------------- timing
def load_timing(script, align):
    text = "\n\n".join(l["text"] for l in script["lines"])
    chars = "".join(align["characters"])
    assert chars == text, "alignment does not match script"
    st, en = align["character_start_times_seconds"], align["character_end_times_seconds"]
    lines, pos = [], 0
    for l in script["lines"]:
        i = text.index(l["text"], pos)
        j = i + len(l["text"]) - 1
        pos = j
        lines.append(dict(l, start=st[i], end=en[j], i=i))

    def word_time(word, after=0.0, end=False):
        k = 0
        while True:
            k = text.find(word, k)
            if k < 0:
                raise KeyError(word)
            if st[k] >= after:
                return en[k + len(word) - 1] if end else st[k]
            k += 1
    return lines, word_time


# ---------------------------------------------------------------- audio
def synth_audio(voice_mp3, total, voice_shift, pause_at, impacts, whooshes, risers, silences, out_wav):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", voice_mp3, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    v = np.frombuffer(raw, np.float32).copy()
    n = int(total * SR)
    voice = np.zeros(n, np.float32)
    cut = int(pause_at * SR)  # insert dramatic pause inside the voice track
    a, b = v[:cut], v[cut:]
    o1 = int(voice_shift * SR)
    voice[o1:o1 + len(a)] = a[: max(0, min(len(a), n - o1))]
    o2 = o1 + len(a) + int(PAUSE_BEFORE * SR)
    voice[o2:o2 + len(b)] = b[: max(0, min(len(b), n - o2))]

    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    # drone: detuned low sines + soft filtered noise, slow swell
    drone = 0.5 * np.sin(2 * np.pi * 55 * t) + 0.4 * np.sin(2 * np.pi * 55.35 * t) + 0.25 * np.sin(2 * np.pi * 82.4 * t)
    noise = rng.standard_normal(n).astype(np.float32)
    k = np.ones(400) / 400
    noise = np.convolve(noise, k, mode="same") * 6
    drone = (drone + 0.35 * noise) * (0.75 + 0.25 * np.sin(2 * np.pi * t / 9))
    # tension pulse in the second half
    pulse = np.sin(2 * np.pi * 110 * t) * (np.sin(2 * np.pi * t * 1.6) > 0.6) * 0.18
    drone = drone + pulse * (t > pause_at + voice_shift)
    env = np.full(n, 0.10, np.float32)
    env[: int(LEAD_IN * SR)] = np.linspace(0.0, 0.22, int(LEAD_IN * SR))
    for s0, s1 in silences:  # full silence moments
        env[int(s0 * SR): int(s1 * SR)] = 0.0
    smooth = np.ones(int(0.05 * SR)) / int(0.05 * SR)
    env = np.convolve(env, smooth, mode="same")
    music = drone * env

    def add(sig, at, gain):
        i = int(at * SR)
        if i >= n:
            return
        m = min(len(sig), n - i)
        music[i:i + m] += sig[:m] * gain

    for at in impacts:  # sub-bass hit with a click
        d = np.arange(int(1.6 * SR)) / SR
        hit = np.sin(2 * np.pi * (48 + 40 * np.exp(-d * 18)) * d) * np.exp(-d * 2.6)
        hit[: int(0.01 * SR)] += rng.standard_normal(int(0.01 * SR)) * 0.6
        add(hit.astype(np.float32), at, 0.9)
    for at in whooshes:
        d = int(0.45 * SR)
        wn = np.convolve(rng.standard_normal(d), np.ones(30) / 30, mode="same")
        add((wn * np.sin(np.linspace(0, np.pi, d)) ** 2).astype(np.float32), at - 0.2, 0.5)
    for at, dur in risers:
        d = int(dur * SR)
        x = np.linspace(0, 1, d)
        sweep = np.sin(2 * np.pi * np.cumsum(200 + 1800 * x ** 2) / SR) * 0.15
        rn = rng.standard_normal(d) * 0.25
        add(((sweep + rn) * x ** 2.2).astype(np.float32), at - dur, 0.45)

    # duck music under the voice
    vol = np.convolve(np.abs(voice), np.ones(int(0.2 * SR)) / int(0.2 * SR), mode="same")
    duck = 1.0 - 0.55 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)
    mix = voice * 1.0 + music * duck * 0.55
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.9
    pcm = (mix * 32767).astype(np.int16)
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- visuals
def prep_image(path):
    im = Image.open(path).convert("RGB")
    s = max(W * 1.25 / im.width, H * 1.25 / im.height)
    return im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)


def camera(im, p, mode, focus=(0.5, 0.5)):
    """Slow push / drift crop of a pre-scaled image. p in 0..1."""
    zw, zh = im.size
    if mode == "push":
        z = 1.0 + 0.10 * p
    elif mode == "fast":
        z = 1.0 + 0.22 * ease(p)
    elif mode == "pull":
        z = 1.12 - 0.10 * p
    else:
        z = 1.04
    cw, ch = W * 1.25 / z / 1.25 * (zw / (W * 1.25)), H * 1.25 / z / 1.25 * (zh / (H * 1.25))
    cw, ch = zw / 1.25 / z, zh / 1.25 / z
    fx, fy = focus
    drift = (p - 0.5) * 0.06 if mode == "drift" else 0
    cx = (zw - cw) * min(max(fx + drift, 0), 1)
    cy = (zh - ch) * fy
    return im.transform((W, H), Image.EXTENT, (cx, cy, cx + cw, cy + ch), Image.BICUBIC)


def grade(frame, mood):
    arr = np.asarray(frame).astype(np.float32)
    if mood in ("calm", "rise", "title"):
        arr = arr * np.array([1.06, 1.0, 0.88])
    elif mood in ("tension", "shock", "reveal"):
        arr = arr * np.array([0.88, 0.97, 1.08])
        g = arr.mean(axis=2, keepdims=True)
        arr = g + (arr - g) * 0.75
    arr = (arr - 128) * 1.08 + 122  # contrast
    return arr


def build_overlays():
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    vign = np.clip(1.10 - 0.35 * d ** 2.2, 0.62, 1.0)[..., None].astype(np.float32)
    rng = np.random.default_rng(1)
    GRAIN = 1.2  # very fine, barely visible: heavy grain looked like noise and wasted bitrate
    grains = [rng.normal(0, GRAIN, (H, W, 1)).astype(np.float32) for _ in range(4)]
    return vign, grains


def text_layer(items, t):
    """items: list of dicts {kind, t0, t1, ...}; returns RGBA overlay or None."""
    active = [it for it in items if it["t0"] <= t < it["t1"]]
    if not active:
        return None
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for it in active:
        age, left = t - it["t0"], it["t1"] - t
        a = min(1.0, age / 0.25, left / 0.3)
        al = int(255 * max(a, 0))
        k = it["kind"]
        if k == "date":  # typewriter date card, lower left
            n = min(len(it["text"]), int(age / 0.045) + 1)
            f = font(SANS, 46, 700)
            d.rectangle([110, H - BAR - 128, 118, H - BAR - 72], fill=GOLD + (al,))
            d.text((140, H - BAR - 100), it["text"][:n], font=f, fill=WHITE + (al,), anchor="lm")
        elif k == "counter":
            p = ease(age / it.get("dur", 1.6))
            val = it["to"] * p
            s = it["fmt"](val)
            sc = 1.0 + 0.04 * (1 - min(1, age / 0.3))
            f = font(SERIF, int(150 * sc))
            d.text((W / 2, H / 2 + 10), s, font=f, fill=GOLD + (al,), anchor="mm")
            if it.get("label"):
                d.text((W / 2, H / 2 + 120), it["label"], font=font(SANS, 34, 600), fill=WHITE + (al,), anchor="mm")
        elif k == "big":  # punchy word (red or gold)
            pop = 1.0 + 0.18 * max(0, 1 - age / 0.18)
            f = font(SERIF if it.get("serif", True) else SANS, int(it.get("size", 170) * pop), 800)
            col = it.get("color", RED)
            d.text((W / 2 + 4, H / 2 + 6), it["text"], font=f, fill=(0, 0, 0, int(al * 0.5)), anchor="mm")
            d.text((W / 2, H / 2), it["text"], font=f, fill=col + (al,), anchor="mm")
            if it.get("sub"):
                d.text((W / 2, H / 2 + 125), it["sub"], font=font(SANS, 36, 600), fill=WHITE + (al,), anchor="mm")
        elif k == "list":  # names stacking in
            f = font(SANS, 44, 700)
            for i, name in enumerate(it["names"]):
                ai = max(0.0, min(1.0, (age - i * it.get("step", 0.35)) / 0.2)) * min(1, left / 0.3)
                if ai <= 0:
                    continue
                y = H / 2 - 120 + i * 80
                x = W - 160
                d.text((x, y), name, font=f, fill=(GOLD if name == it.get("hl") else WHITE) + (int(255 * ai),), anchor="rm")
    return layer


def title_frame(bg, age):
    fr = bg.copy()
    arr = np.asarray(fr).astype(np.float32) * 0.55
    fr = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(fr, "RGBA")
    a = int(255 * min(1, age / 0.6))
    small = font(SANS, 30, 700)
    txt = "F I R M E N F R I E D H O F"
    d.text((W / 2, H / 2 - 150), txt, font=small, fill=(170, 176, 188, a), anchor="mm")
    sc = 1.06 - 0.06 * ease(age / 1.2)
    d.text((W / 2, H / 2 - 20), "WIRECARD", font=font(SERIF, int(190 * sc)), fill=GOLD + (a,), anchor="mm")
    a2 = int(255 * min(1, max(0, (age - 0.5) / 0.6)))
    d.text((W / 2, H / 2 + 105), "Die Firma, die es nie gab", font=font(SANS, 48, 500), fill=WHITE + (a2,), anchor="mm")
    d.line([(W / 2 - 260, H / 2 + 165), (W / 2 + 260, H / 2 + 165)], fill=GOLD + (a2,), width=3)
    return fr


def chapter_frame(age):
    fr = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(fr, "RGBA")
    a = int(255 * min(1, age / 0.4))
    d.text((W / 2, H / 2 - 70), "KAPITEL 1", font=font(SANS, 40, 700), fill=GOLD + (a,), anchor="mm")
    a2 = int(255 * min(1, max(0, (age - 0.25) / 0.5)))
    d.text((W / 2, H / 2 + 30), "Der Aufstieg", font=font(SERIF, 130), fill=WHITE + (a2,), anchor="mm")
    return fr


def main(img_dir, voice_mp3, align_json, out_mp4):
    script = json.load(open(os.path.join(ROOT, "test/script_wirecard_test.json")))
    prompts = json.load(open(os.path.join(ROOT, "test/image_prompts.json")))["shots"]
    align = json.load(open(align_json))
    lines, wt = load_timing(script, align)
    L = {l["id"]: l for l in lines}

    pause_at = (L["l03"]["end"] + L["l04"]["start"]) / 2  # original voice time of the dramatic pause

    def T(x):  # map voice time -> video time
        return x + LEAD_IN + (PAUSE_BEFORE if x >= pause_at else 0)

    voice_end = T(L["l09"]["end"])
    title_t0 = voice_end + 0.35
    chapter_t0 = title_t0 + TITLE_LEN
    total = chapter_t0 + CHAPTER_LEN

    # --- shots: split each line's span across its images
    by_line = {}
    for s in prompts:
        by_line.setdefault(s["line"], []).append(s["id"])
    shots = []
    for idx, l in enumerate(lines):
        ids = by_line.get(l["id"], [])
        if not ids:
            continue
        t0 = 0.0 if idx == 0 else T(l["start"]) - 0.15
        t1 = T(lines[idx + 1]["start"]) - 0.15 if idx + 1 < len(lines) else title_t0
        if l["id"] == "l04":
            t0 = T(pause_at) - 0.2  # vault appears in the silence
        seg = (t1 - t0) / len(ids)
        for k, sid in enumerate(ids):
            mode = {"calm": "push", "rise": "drift", "tension": "push", "shock": "fast", "reveal": "pull", "title": "push"}[l["mood"]]
            shots.append(dict(id=sid, t0=t0 + k * seg, t1=t0 + (k + 1) * seg, mood=l["mood"], mode=mode))
    # make shots contiguous
    for a_, b_ in zip(shots, shots[1:]):
        a_["t1"] = b_["t0"]

    imgs = {}
    for s in shots:
        p = None
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            q = os.path.join(img_dir, s["id"] + ext)
            if os.path.exists(q):
                p = q
        imgs[s["id"]] = prep_image(p)
    title_bg = camera(imgs[by_line["l09"][-1]], 0.5, "push")

    # --- text overlays (key words only)
    fmt_mrd = lambda v: f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " MRD. €"
    items = [
        dict(kind="date", text="SEPTEMBER 2018", t0=T(0.2), t1=T(L["l01"]["start"] + 4.2)),
        dict(kind="counter", to=24.6, fmt=fmt_mrd, label="Börsenwert", t0=T(wt("fünfundzwanzig")) - 0.1,
             t1=T(L["l02"]["start"]) - 0.1, dur=1.4),
        dict(kind="list", names=["SIEMENS", "VOLKSWAGEN", "DEUTSCHE BANK", "WIRECARD"], hl="WIRECARD",
             t0=T(wt("neben")), t1=T(L["l02"]["end"]) + 0.3),
        dict(kind="date", text="18. JUNI 2020", t0=T(wt("achtzehnten")) - 0.1, t1=T(wt("fehlen"))),
        dict(kind="big", text="1,9 MRD. €", color=RED, sub="fehlen in der Bilanz", t0=T(wt("eins Komma")) - 0.05,
             t1=T(L["l03"]["end"]) + 0.25),
        dict(kind="big", text="PLEITE", color=RED, size=200, t0=T(wt("pleite")), t1=T(wt("pleite")) + 1.4),
        dict(kind="big", text="ERSTES DAX-UNTERNEHMEN", color=WHITE, serif=False, size=70,
             t0=T(wt("erstes")), t1=T(L["l06"]["end"]) + 0.3),
        dict(kind="big", text="GESUCHT", color=RED, size=190, t0=T(wt("gesucht")), t1=T(L["l07"]["end"]) + 0.35),
    ]

    impacts = [T(wt("Milliarden", after=L["l01"]["start"], end=True)) - 0.1, T(wt("eins Komma")) - 0.05,
               T(L["l04"]["start"]) - 0.02, T(wt("pleite")), T(wt("gesucht")), title_t0]
    whooshes = [it["t0"] for it in items if it["kind"] in ("date", "list")] + [chapter_t0]
    risers = [(title_t0, 2.2)]
    silences = [(T(pause_at) - 0.05, T(L["l04"]["start"]) - 0.05)]

    work = os.path.join(ROOT, "work")
    os.makedirs(work, exist_ok=True)
    wav = os.path.join(work, "mix.wav")
    synth_audio(voice_mp3, total, LEAD_IN, pause_at, impacts, whooshes, risers, silences, wav)

    vign, grains = build_overlays()
    nframes = int(total * FPS)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "12M", "-bufsize", "24M",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", out_mp4],
                           stdin=subprocess.PIPE)
    flash_ts = [title_t0]
    for fi in range(nframes):
        t = fi / FPS
        if t >= chapter_t0:
            fr = chapter_frame(t - chapter_t0)
            arr = np.asarray(fr).astype(np.float32)
            bars = False
        elif t >= title_t0:
            fr = title_frame(title_bg, t - title_t0)
            arr = np.asarray(fr).astype(np.float32)
            bars = True
        else:
            s = next((x for x in shots if x["t0"] <= t < x["t1"]), shots[-1])
            p = (t - s["t0"]) / max(0.01, s["t1"] - s["t0"])
            if t < LEAD_IN:  # fade up from black
                pass
            fr = camera(imgs[s["id"]], p, s["mode"])
            ov = text_layer(items, t)
            if ov is not None:
                fr = fr.convert("RGBA")
                fr.alpha_composite(ov)
                fr = fr.convert("RGB")
            arr = grade(fr, s["mood"])
            bars = True
        arr = arr * vign + grains[fi % len(grains)]
        if t < LEAD_IN:
            arr *= ease(t / LEAD_IN)
        for ft in flash_ts:  # light-leak flash
            if 0 <= t - ft < 0.5:
                k_ = 1 - (t - ft) / 0.5
                arr = arr + np.array([255, 170, 80]) * 0.32 * k_
        if t >= chapter_t0 - 0.12 and t < chapter_t0:  # dip to black between title and chapter
            arr *= 0.2
        if bars:
            arr[:BAR] = 0
            arr[H - BAR:] = 0
        enc.stdin.write(arr.clip(0, 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()
    print("done", out_mp4, round(total, 2), "s")


if __name__ == "__main__":
    main(*sys.argv[1:5])
