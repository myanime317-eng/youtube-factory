"""Firmenfriedhof editor v3.

Adds to the test editor: 2.5D depth parallax on stills, Flow video clips where available,
animated graphics (stock chart, route map), readable text with shadow glow, whip transitions,
and real sound effects / music when assets/sound has them.

Usage: python3 editor/make_video_v3.py <images_dir> <voice.mp3> <alignment.json> <out.mp4>
"""
import json, os, subprocess, sys, wave, urllib.request
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_test_video as base  # noqa: E402
import graphics  # noqa: E402
from make_test_video import (W, H, FPS, SR, ROOT, SERIF, SANS, GOLD, WHITE, RED, BAR, LEAD_IN, PAUSE_BEFORE,
                             TITLE_LEN, CHAPTER_LEN, font, ease, load_timing, grade, build_overlays,
                             title_frame, chapter_frame)

DEPTH_URL = "https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/v2.0.0/depth_anything_v2_vits.onnx"
DEPTH_MODEL = os.environ.get("DEPTH_MODEL", os.path.expanduser("~/.cache/firmenfriedhof/depth_vits.onnx"))
SOUND = os.path.join(ROOT, "assets", "sound")
WORK = os.path.join(ROOT, "work")


# ---------------------------------------------------------------- depth + parallax
_sess = None


def depth_map(path, size):
    """Relative depth (1 = near) for an image, cached next to the work files."""
    global _sess
    cache = os.path.join(WORK, "depth", os.path.basename(path) + ".npy")
    if os.path.exists(cache):
        d = np.load(cache)
    else:
        import onnxruntime as ort
        if not os.path.exists(DEPTH_MODEL):
            os.makedirs(os.path.dirname(DEPTH_MODEL), exist_ok=True)
            urllib.request.urlretrieve(DEPTH_URL, DEPTH_MODEL)
        if _sess is None:
            _sess = ort.InferenceSession(DEPTH_MODEL, providers=["CPUExecutionProvider"])
        im = Image.open(path).convert("RGB").resize((518, 518), Image.BICUBIC)
        x = np.asarray(im, np.float32) / 255
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
        d = _sess.run(None, {_sess.get_inputs()[0].name: x})[0].squeeze()
        d = (d - d.min()) / (d.max() - d.min() + 1e-6)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        np.save(cache, d.astype(np.float16))
    d = cv2.resize(d.astype(np.float32), size, interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(d, (0, 0), 6)  # soft edges = fewer tearing artifacts


class Still:
    """A still image that moves like a camera shot: zoom + depth parallax."""

    def __init__(self, path):
        im = Image.open(path).convert("RGB")
        s = max(W * 1.2 / im.width, H * 1.2 / im.height)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        self.img = np.asarray(im)
        self.h, self.w = self.img.shape[:2]
        self.depth = depth_map(path, (self.w, self.h))
        gy, gx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.u = (gx - W / 2) / W  # -0.5..0.5
        self.v = (gy - H / 2) / H

    def frame(self, p, mode):
        # base framing: how much of the (1.2x) image we see, and where
        z = {"push": 1.0 + 0.08 * p, "fast": 1.0 + 0.16 * ease(p), "pull": 1.10 - 0.08 * p}.get(mode, 1.04)
        cw, ch = self.w / 1.2 / z, self.h / 1.2 / z
        drift = (p - 0.5) * 0.05 * self.w if mode == "drift" else 0.0
        cx, cy = self.w / 2 + drift, self.h / 2
        sx = cx + self.u * cw
        sy = cy + self.v * ch
        # parallax: near pixels move more than far ones as the camera moves
        d = cv2.remap(self.depth, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        par = {"push": 0.045, "fast": 0.07, "pull": -0.045}.get(mode, 0.0) * (p - 0.5)
        k = 1.0 / (1.0 + par * (d - 0.35) * 2.0)
        sx = cx + self.u * cw * k
        sy = cy + self.v * ch * k
        if mode == "drift":  # sideways parallax: foreground slides further than background
            sx = sx + (d - 0.4) * (p - 0.5) * 0.06 * cw
        out = cv2.remap(self.img, sx, sy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        return Image.fromarray(out)


class Clip:
    """A Flow video clip, read frame by frame and fitted to the shot length."""

    def __init__(self, path, length):
        self.path, self.length = path, length
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nk=1:nw=1", path], capture_output=True, text=True)
        self.dur = float(probe.stdout.strip() or 5)
        # play at natural speed, or slower if the shot is longer than the clip
        speed = min(1.0, self.dur / max(length, 0.1))
        vf = (f"setpts=PTS/{speed},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},unsharp=5:5:0.6")
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", vf, "-f", "rawvideo",
                                      "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = None

    def frame(self, p, mode):
        buf = self.proc.stdout.read(W * H * 3)
        if len(buf) == W * H * 3:
            self.last = Image.frombuffer("RGB", (W, H), buf)
        return self.last if self.last is not None else Image.new("RGB", (W, H))

    def close(self):
        try:
            self.proc.kill()
        except Exception:
            pass


class Graphic:
    def __init__(self, kind):
        self.kind = kind

    def frame(self, p, mode):
        if self.kind == "chart_peak":
            return graphics.chart_frame(p, "peak")
        if self.kind == "chart_crash":
            return graphics.chart_frame(p, "crash")
        if self.kind == "map":
            return graphics.map_frame(p)
        raise ValueError(self.kind)


# ---------------------------------------------------------------- text
def text_layer(items, t):
    active = [it for it in items if it["t0"] <= t < it["t1"]]
    if not active:
        return None
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for it in active:
        age, left = t - it["t0"], it["t1"] - t
        al = int(255 * max(0.0, min(1.0, age / 0.22, left / 0.25)))
        k = it["kind"]
        if k == "date":
            n = min(len(it["text"]), int(age / 0.045) + 1)
            d.rectangle([110, H - BAR - 132, 118, H - BAR - 68], fill=GOLD + (al,))
            d.text((140, H - BAR - 100), it["text"][:n], font=font(SANS, 48, 800), fill=WHITE + (al,), anchor="lm")
        elif k == "counter":
            p = ease(age / it.get("dur", 1.6))
            sc = 1.0 + 0.04 * (1 - min(1, age / 0.3))
            cy = it.get("y", H / 2 - 20)
            d.text((W / 2, cy), it["fmt"](it["to"] * p), font=font(SERIF, int(150 * sc)),
                   fill=GOLD + (al,), anchor="mm")
            if it.get("label"):
                d.text((W / 2, cy + 95), it["label"].upper(), font=font(SANS, 32, 700),
                       fill=WHITE + (al,), anchor="mm")
        elif k == "big":
            pop = 1.0 + 0.16 * max(0, 1 - age / 0.16)
            f = font(SERIF if it.get("serif", True) else SANS, int(it.get("size", 170) * pop), 800)
            y = H / 2 + it.get("dy", 0)
            if it.get("band", True):  # dark cinematic band so the word reads on bright pictures
                band = Image.new("L", (W, 1))
                band.putdata([int(min(1, (1 - abs(x - W / 2) / (W / 2)) * 1.6) * 0 + 175 * min(1.0, (1 - abs(x - W / 2) / (W / 2)) * 1.6)) for x in range(W)])
                hh = 300 if it.get("sub") else 230
                band = band.resize((W, hh))
                ba = np.asarray(band, np.float32) * (al / 255)
                yy = np.linspace(-1, 1, hh)[:, None]
                ba = ba * np.clip(1.4 - np.abs(yy) * 1.4, 0, 1)
                blk = Image.new("RGBA", (W, hh), (0, 0, 0, 0))
                blk.putalpha(Image.fromarray(ba.clip(0, 255).astype(np.uint8)))
                layer.alpha_composite(blk, (0, int(y - hh / 2 + (45 if it.get("sub") else 0))))
            d.text((W / 2, y), it["text"], font=f, fill=it.get("color", RED) + (al,), anchor="mm")
            if it.get("sub"):
                d.text((W / 2, y + 120), it["sub"], font=font(SANS, 38, 700), fill=WHITE + (al,), anchor="mm")
        elif k == "list":
            f = font(SANS, 46, 800)
            for i, name in enumerate(it["names"]):
                ai = max(0.0, min(1.0, (age - i * it.get("step", 0.35)) / 0.2)) * min(1, left / 0.3)
                if ai <= 0:
                    continue
                slide = (1 - ease(min(1, (age - i * it.get("step", 0.35)) / 0.25))) * 60
                y = H / 2 - 130 + i * 84
                hl = name == it.get("hl")
                d.rectangle([W - 150, y - 26, W - 144, y + 26], fill=(GOLD if hl else WHITE) + (int(255 * ai),))
                d.text((W - 170 + slide, y), name, font=f, fill=(GOLD if hl else WHITE) + (int(255 * ai),), anchor="rm")
    # dark glow behind all text so it reads on any picture
    a = layer.split()[3]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(16)).point(lambda v: min(255, int(v * 1.6))))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    return out


# ---------------------------------------------------------------- audio
def load_sound(name):
    path = os.path.join(SOUND, name + ".mp3")
    if not os.path.exists(path):
        return None
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def build_audio(voice_mp3, total, pause_at, cues, silences, out_wav):
    """cues: list of (time, sound_name, gain). Falls back to the synthetic kit when a sound is missing."""
    have_kit = os.path.exists(os.path.join(SOUND, "impact_1.mp3"))
    if not have_kit:  # old synthetic sound design
        impacts = [c[0] for c in cues if c[1].startswith(("impact", "braam"))]
        whooshes = [c[0] for c in cues if c[1].startswith("whoosh")]
        risers = [(c[0] + 4.0, 2.2) for c in cues if c[1].startswith("riser")]
        return base.synth_audio(voice_mp3, total, LEAD_IN, pause_at, impacts, whooshes, risers, silences, out_wav)

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", voice_mp3, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    v = np.frombuffer(raw, np.float32).copy()
    n = int(total * SR)
    voice = np.zeros(n, np.float32)
    cut = int(pause_at * SR)
    a, b = v[:cut], v[cut:]
    o1 = int(LEAD_IN * SR)
    voice[o1:o1 + len(a)] = a[: max(0, min(len(a), n - o1))]
    o2 = o1 + len(a) + int(PAUSE_BEFORE * SR)
    voice[o2:o2 + len(b)] = b[: max(0, min(len(b), n - o2))]

    music = np.zeros(n, np.float32)
    bed = load_sound("music_dark_1")
    if bed is not None:
        m = min(n, len(bed))
        music[:m] = bed[:m] * 0.5
        fade = int(1.5 * SR)
        music[:fade] *= np.linspace(0, 1, fade)
    for s0, s1 in silences:
        i0, i1 = int(s0 * SR), int(s1 * SR)
        ramp = int(0.08 * SR)
        music[i0 - ramp:i0] *= np.linspace(1, 0, ramp)
        music[i0:i1] = 0
    sfx = np.zeros(n, np.float32)
    for at, name, gain in cues:
        s = load_sound(name)
        if s is None:
            continue
        i = int(max(0, at) * SR)
        if i >= n:
            continue
        m = min(len(s), n - i)
        sfx[i:i + m] += s[:m] * gain
    vol = np.convolve(np.abs(voice), np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    duck = 1.0 - 0.6 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)
    mix = voice * 1.0 + music * duck * 0.45 + sfx * 0.55
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.9
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- main
def main(img_dir, voice_mp3, align_json, out_mp4):
    script = json.load(open(os.path.join(ROOT, "test/script_wirecard_test.json")))
    spec = json.load(open(os.path.join(ROOT, "test/image_prompts.json")))
    prompts = spec["shots"]
    clip_spec = os.path.join(ROOT, "test/clip_prompts.json")
    clips = {}
    if os.path.exists(clip_spec):
        cs = json.load(open(clip_spec))
        for c in cs["clips"]:
            f = os.path.join(ROOT, cs["clips_out"], c["id"] + ".mp4")
            if os.path.exists(f):
                clips[c["shot"]] = f
    graphics_for = {"s03": "chart_peak", "s11": "map", "s14": "chart_crash"}

    align = json.load(open(align_json))
    lines, wt = load_timing(script, align)
    L = {l["id"]: l for l in lines}
    pause_at = (L["l03"]["end"] + L["l04"]["start"]) / 2

    def T(x):
        return x + LEAD_IN + (PAUSE_BEFORE if x >= pause_at else 0)

    voice_end = T(L["l09"]["end"])
    title_t0 = voice_end + 0.35
    chapter_t0 = title_t0 + TITLE_LEN
    total = chapter_t0 + CHAPTER_LEN

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
            t0 = T(pause_at) - 0.2
        # graphics and clips get more time than plain stills
        weights = [1.5 if (sid in graphics_for or sid in clips) else 1.0 for sid in ids]
        acc = t0
        for k, sid in enumerate(ids):
            dur = (t1 - t0) * weights[k] / sum(weights)
            mode = {"calm": "push", "rise": "drift", "tension": "push", "shock": "fast", "reveal": "pull",
                    "title": "push"}[l["mood"]]
            shots.append(dict(id=sid, t0=acc, t1=acc + dur, mood=l["mood"], mode=mode,
                              whip_in=(k == 0 and l["mood"] in ("rise", "shock"))))
            acc += dur
    for a_, b_ in zip(shots, shots[1:]):
        a_["t1"] = b_["t0"]

    def find_img(sid):
        for ext in (".jpg", ".png", ".jpeg", ".webp"):
            q = os.path.join(img_dir, sid + ext)
            if os.path.exists(q):
                return q
        raise FileNotFoundError(sid)

    print("depth + stills ...", flush=True)
    stills = {s["id"]: Still(find_img(s["id"])) for s in shots if s["id"] not in graphics_for}
    title_img = base.prep_image(find_img(by_line["l09"][-1]))
    title_bg = base.camera(title_img, 0.5, "push")

    fmt_mrd = lambda v: f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " MRD. €"
    items = [
        dict(kind="date", text="SEPTEMBER 2018", t0=T(0.2), t1=T(L["l01"]["start"] + 4.2)),
        dict(kind="counter", to=24.6, fmt=fmt_mrd, label="Börsenwert", y=255, t0=T(wt("fünfundzwanzig")) - 0.1,
             t1=T(L["l02"]["start"]) - 0.1, dur=1.4),
        dict(kind="list", names=["SIEMENS", "VOLKSWAGEN", "DEUTSCHE BANK", "WIRECARD"], hl="WIRECARD",
             t0=T(wt("neben")), t1=T(L["l02"]["end"]) + 0.3),
        dict(kind="date", text="18. JUNI 2020", t0=T(wt("achtzehnten")) - 0.1, t1=T(wt("fehlen"))),
        dict(kind="big", text="1,9 MRD. €", color=RED, sub="fehlen in der Bilanz", t0=T(wt("eins Komma")) - 0.05,
             t1=T(L["l03"]["end"]) + 0.25),
        dict(kind="big", text="PLEITE", color=RED, size=210, dy=-40, t0=T(wt("pleite")),
             t1=T(wt("erstes")) - 0.05),
        dict(kind="big", text="ERSTES DAX-UNTERNEHMEN", color=WHITE, serif=False, size=72, dy=-40,
             sub="der Geschichte", t0=T(wt("erstes")), t1=T(L["l06"]["end"]) + 0.3),
        dict(kind="big", text="GESUCHT", color=RED, size=200, t0=T(wt("gesucht")), t1=T(L["l07"]["end"]) + 0.35),
    ]

    cues = [
        (T(wt("Milliarden", after=L["l01"]["start"], end=True)) - 0.15, "impact_2", 0.9),
        (T(wt("neben")) - 0.1, "whoosh_1", 0.7),
        (T(wt("achtzehnten")) - 0.1, "typing_1", 0.5),
        (T(wt("eins Komma")) - 0.1, "impact_1", 1.0),
        (T(L["l04"]["start"]) - 0.05, "braam_1", 1.0),
        (T(wt("pleite")) - 0.05, "impact_1", 1.0),
        (T(wt("pleite")) + 0.1, "paper_1", 0.6),
        (T(wt("Chef")), "camera_1", 0.5),
        (T(wt("Privatjet")) - 0.2, "jet_1", 0.55),
        (T(wt("gesucht")) - 0.05, "impact_2", 0.9),
        (title_t0 - 4.0, "riser_1", 0.8),
        (title_t0, "impact_1", 1.0),
        (chapter_t0 - 0.1, "whoosh_2", 0.8),
    ] + [(s["t0"] - 0.15, "whoosh_2", 0.55) for s in shots if s["whip_in"]]
    silences = [(T(pause_at) - 0.05, T(L["l04"]["start"]) - 0.05)]

    os.makedirs(WORK, exist_ok=True)
    wav = os.path.join(WORK, "mix_v3.wav")
    build_audio(voice_mp3, total, pause_at, cues, silences, wav)

    vign, grains = build_overlays()
    nframes = int(total * FPS)
    tmp = out_mp4 + ".part.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "19", "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp],
                           stdin=subprocess.PIPE)
    sources, cur = {}, None
    WHIP = 0.16
    for fi in range(nframes):
        t = fi / FPS
        bars = True
        if t >= chapter_t0:
            arr = np.asarray(chapter_frame(t - chapter_t0)).astype(np.float32)
            bars = False
        elif t >= title_t0:
            arr = np.asarray(title_frame(title_bg, t - title_t0)).astype(np.float32)
        else:
            si = next((i for i, x in enumerate(shots) if x["t0"] <= t < x["t1"]), len(shots) - 1)
            s = shots[si]
            if cur != s["id"]:
                if cur in sources and isinstance(sources[cur], Clip):
                    sources[cur].close()
                cur = s["id"]
                if cur in graphics_for:
                    sources[cur] = Graphic(graphics_for[cur])
                elif cur in clips:
                    sources[cur] = Clip(clips[cur], s["t1"] - s["t0"])
                else:
                    sources[cur] = stills[cur]
            p = (t - s["t0"]) / max(0.01, s["t1"] - s["t0"])
            fr = sources[cur].frame(p, s["mode"])
            ov = text_layer(items, t)
            if ov is not None:
                fr = fr.convert("RGBA")
                fr.alpha_composite(ov)
                fr = fr.convert("RGB")
            arr = grade(fr, "none" if cur in graphics_for else s["mood"])
            # whip-pan into the first shot of a rise/shock line
            if s["whip_in"] and t - s["t0"] < WHIP:
                k = 1 - (t - s["t0"]) / WHIP
                shift = int(W * 0.25 * k * k)
                arr = np.roll(arr, -shift, axis=1)
                ks = max(1, int(120 * k))
                arr = cv2.blur(arr, (ks, 1))
            nxt = shots[si + 1] if si + 1 < len(shots) else None
            if nxt and nxt["whip_in"] and s["t1"] - t < WHIP:
                k = 1 - (s["t1"] - t) / WHIP
                arr = np.roll(arr, int(W * 0.25 * k * k), axis=1)
                arr = cv2.blur(arr, (max(1, int(120 * k)), 1))
        arr = arr * vign + grains[fi % len(grains)]
        if t < LEAD_IN:
            arr *= ease(t / LEAD_IN)
        if 0 <= t - title_t0 < 0.5:
            arr = arr + np.array([255, 170, 80]) * 0.30 * (1 - (t - title_t0) / 0.5)
        if chapter_t0 - 0.12 <= t < chapter_t0:
            arr *= 0.2
        if bars:
            arr[:BAR] = 0
            arr[H - BAR:] = 0
        enc.stdin.write(arr.clip(0, 255).astype(np.uint8).tobytes())
        if fi % 300 == 0:
            print(f"frame {fi}/{nframes}", flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("encoder failed")
    os.replace(tmp, out_mp4)
    print("done", out_mp4, round(total, 2), "s")


if __name__ == "__main__":
    main(*sys.argv[1:5])
