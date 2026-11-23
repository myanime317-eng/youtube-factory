"""Firmenfriedhof episode editor: renders a full episode from a job folder.

jobs/<slug>/script.json   lines with text, tags, mood, shots, overlays, sfx, chapter/title cards, music
jobs/<slug>/image_prompts.json + flow_img/   still images (from the laptop helper)
jobs/<slug>/clip_prompts.json + flow_clips/  optional Flow video clips (used where present)
jobs/<slug>/voice.mp3 + voice_alignment.json narration (scripts/voice_v3.py)

Usage: python3 editor/render_episode.py jobs/<slug> out.mp4 [--workers N] [--until SECONDS]
Renders in parallel chunks (one mp4 per chunk), joins them with -c copy, then adds the sound.
See docs/JOB_FORMAT.md for the script format.
"""
import argparse, json, math, os, subprocess, sys, wave
import multiprocessing as mp
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graphics  # noqa: E402
import make_test_video as base  # noqa: E402
from make_test_video import W, H, FPS, SR, SERIF, SANS, GOLD, WHITE, RED, NAVY, BAR, font, ease, grade, build_overlays  # noqa: E402
from make_video_v3 import Still, Clip, text_layer, load_sound, depth_map  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAD_IN, TITLE_LEN, CHAPTER_LEN, OUTRO_LEN = 1.2, 4.5, 3.0, 4.0
MODE = {"calm": "push", "rise": "drift", "tension": "push", "shock": "fast", "reveal": "pull",
        "reflective": "pull", "title": "push"}
COLORS = {"red": RED, "gold": GOLD, "white": WHITE}


# ---------------------------------------------------------------- timeline
class Timeline:
    """Maps narration time to video time, with gaps for pauses, chapter cards and the title card."""

    def __init__(self, job):
        self.job = job
        sc = json.load(open(os.path.join(job, "script.json")))
        al = json.load(open(os.path.join(job, "voice_alignment.json")))
        self.script = sc
        text = "\n\n".join(l["text"] for l in sc["lines"])
        st, en = al["character_start_times_seconds"], al["character_end_times_seconds"]
        assert "".join(al["characters"]) == text, "alignment does not match script"
        self.text, self.st, self.en = text, st, en
        lines, pos = [], 0
        for l in sc["lines"]:
            i = text.index(l["text"], pos)
            j = i + len(l["text"]) - 1
            pos = j
            lines.append(dict(l, start=st[i], end=en[j], i=i, j=j))
        self.lines = lines
        gaps = []  # (voice_time, length, kind, payload)
        for k, l in enumerate(lines):
            prev_end = lines[k - 1]["end"] if k else 0.0
            at = (prev_end + l["start"]) / 2 if k else 0.0
            if l.get("chapter"):
                gaps.append((at, CHAPTER_LEN, "chapter", l["chapter"]))
            if l.get("pause_before"):
                gaps.append((at + 1e-4, float(l["pause_before"]), "pause", None))
            if l.get("title_card"):
                nxt = lines[k + 1]["start"] if k + 1 < len(lines) else l["end"] + 0.5
                gaps.append(((l["end"] + nxt) / 2, TITLE_LEN, "title", l))
        self.gaps = sorted(gaps, key=lambda g: g[0])
        self.voice_end = lines[-1]["end"]
        self.total = self.T(self.voice_end) + 0.8 + OUTRO_LEN

    def T(self, x):
        return x + LEAD_IN + sum(g[1] for g in self.gaps if g[0] < x)

    def gap_windows(self):
        """Video-time windows of each gap: (t0, t1, kind, payload)."""
        out = []
        for g in self.gaps:
            t0 = g[0] + LEAD_IN + sum(h[1] for h in self.gaps if h[0] < g[0])
            out.append((t0, t0 + g[1], g[2], g[3]))
        return out

    def word(self, line, w, end=False):
        """Narration time of word `w` inside line (first match), else the line start."""
        seg = self.text[line["i"]: line["j"] + 1]
        k = seg.lower().find(w.lower())
        if k < 0:
            return line["end"] if end else line["start"]
        k += line["i"]
        return self.en[k + len(w) - 1] if end else self.st[k]


# ---------------------------------------------------------------- plan
def build_plan(job):
    tl = Timeline(job)
    windows = tl.gap_windows()
    clips = {}
    cpath = os.path.join(job, "clip_prompts.json")
    if os.path.exists(cpath):
        cs = json.load(open(cpath))
        for c in cs["clips"]:
            f = os.path.join(ROOT, cs["clips_out"], c["id"] + ".mp4")
            if os.path.exists(f):
                clips[c["shot"]] = f
    img_dir = os.path.join(job, "flow_img")

    shots = []
    for k, l in enumerate(tl.lines):
        t0 = 0.0 if k == 0 else tl.T(l["start"]) - 0.15
        t1 = tl.T(tl.lines[k + 1]["start"]) - 0.15 if k + 1 < len(tl.lines) else tl.T(tl.voice_end) + 0.8
        # a gap (card / pause) inside this span cuts it short
        for w0, w1, kind, _ in windows:
            if t0 < w0 < t1 and kind != "pause":  # pauses keep the current picture running
                t1 = min(t1, w0)
            if kind != "pause" and w0 <= t0 < w1:
                t0 = w1
        specs = l.get("shots") or []
        if not specs:
            continue
        weights = [1.6 if isinstance(s, dict) or s in clips else 1.0 for s in specs]
        acc = t0
        for n, s in enumerate(specs):
            dur = (t1 - t0) * weights[n] / sum(weights)
            shots.append(dict(spec=s, t0=acc, t1=acc + dur, mood=l.get("mood", "calm"),
                              mode=MODE.get(l.get("mood", "calm"), "push"), whip=(n == 0 and l.get("mood") in ("rise", "shock"))))
            acc += dur
    for a, b in zip(shots, shots[1:]):
        a["t1"] = b["t0"]

    items, cues = [], []
    for k, l in enumerate(tl.lines):
        nxt = tl.lines[k + 1]["start"] if k + 1 < len(tl.lines) else l["end"] + 1
        for o in l.get("overlays", []):
            at = tl.T(tl.word(l, o.get("at", ""))) - 0.08
            if o.get("until"):
                end = tl.T(tl.word(l, o["until"], end=True)) + 0.3
            elif o["kind"] in ("date", "lower"):
                end = at + o.get("dur", 3.2)
            else:
                end = tl.T(l["end"]) + 0.35
            it = dict(o, t0=at, t1=max(end, at + 1.2))
            if it["kind"] == "big":
                it["color"] = COLORS.get(o.get("color", "red"), RED)
                it["serif"] = o.get("serif", len(o["text"]) < 14)
                it["size"] = o.get("size", 190 if len(o["text"]) < 10 else (120 if len(o["text"]) < 16 else 72))
            if it["kind"] == "counter":
                unit = o.get("unit", "")
                dec = o.get("decimals", 1)
                it["fmt"] = (lambda u, dc: (lambda v: f"{v:,.{dc}f}".replace(",", "X").replace(".", ",").replace("X", ".") + (" " + u if u else "")))(unit, dec)
                it.setdefault("dur", 1.4)
            items.append(it)
        for s in l.get("sfx", []):
            cues.append((tl.T(tl.word(l, s.get("at", ""))) - 0.06, s["name"], s.get("gain", 0.9)))
    # no two overlays at the same time: earlier one ends when the next starts
    items.sort(key=lambda i: i["t0"])
    for a, b in zip(items, items[1:]):
        if a["t1"] > b["t0"] and a["kind"] in ("big", "counter") and b["kind"] in ("big", "counter"):
            a["t1"] = b["t0"] - 0.02
    for w0, w1, kind, _ in windows:
        if kind == "chapter":
            cues += [(w0 - 0.1, "whoosh_2", 0.8), (w0 + 0.25, "impact_2", 0.7)]
        elif kind == "title":
            cues += [(w0 - 4.0, "riser_1", 0.8), (w0, "impact_1", 1.0)]
    for s in shots:
        if s["whip"]:
            cues.append((s["t0"] - 0.15, "whoosh_1", 0.5))
    return tl, shots, items, cues, clips, img_dir, windows


# ---------------------------------------------------------------- audio
def build_audio(job, tl, cues, windows, out_wav):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", os.path.join(job, "voice.mp3"), "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    v = np.frombuffer(raw, np.float32)
    n = int(tl.total * SR) + SR
    voice = np.zeros(n, np.float32)
    cuts = [0.0] + [g[0] for g in tl.gaps] + [len(v) / SR]
    for a, b in zip(cuts, cuts[1:]):
        seg = v[int(a * SR): int(b * SR)]
        o = int(tl.T(a + 1e-6) * SR)
        m = max(0, min(len(seg), n - o))
        voice[o:o + m] += seg[:m]

    # music: one bed per section, switched by "music" keys on lines, looped, crossfaded
    sections, cur = [], "intro"
    for l in tl.lines:
        if l.get("music"):
            cur = l["music"]
        if not sections or sections[-1][1] != cur:
            sections.append((tl.T(l["start"]) - (1.0 if sections else tl.T(l["start"])), cur))
    sections.append((tl.total, None))
    music = np.zeros(n, np.float32)
    fade = int(1.5 * SR)
    for (t0, name), (t1, _) in zip(sections, sections[1:]):
        track = load_sound("music_" + name + "_1") if name else None
        if track is None:
            track = load_sound("music_dark_1")
        if track is None:
            continue
        i0, i1 = int(max(0, t0) * SR), int(t1 * SR) + fade
        L = i1 - i0
        reps = int(math.ceil(L / len(track))) + 1
        bed = np.tile(track, reps)[:L].copy()
        env = np.ones(L, np.float32)
        env[:fade] = np.linspace(0, 1, fade) if t0 > 0 else env[:fade]
        env[-fade:] = np.linspace(1, 0, fade)
        m = min(L, n - i0)
        music[i0:i0 + m] += (bed * env)[:m] * 0.5
    for w0, w1, kind, _ in windows:  # dramatic silence before a reveal
        if kind == "pause":
            i0, i1 = int(w0 * SR), int(w1 * SR)
            r = int(0.08 * SR)
            music[max(0, i0 - r):i0] *= np.linspace(1, 0, min(r, i0))
            music[i0:i1] = 0
    end_i = int((tl.total - 1.5) * SR)
    music[end_i:] *= np.linspace(1, 0, n - end_i)

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
    duck = 1.0 - 0.6 * np.clip(vol / (np.percentile(vol, 99) * 0.25 + 1e-9), 0, 1)
    mix = voice + music * duck * 0.42 + sfx * 0.5
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.9
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix[: int(tl.total * SR)] * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- frames
def chapter_card(n, title, age):
    fr = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(fr, "RGBA")
    a = int(255 * min(1, age / 0.4))
    d.text((W / 2, H / 2 - 70), f"KAPITEL {n}", font=font(SANS, 40, 700), fill=GOLD + (a,), anchor="mm")
    a2 = int(255 * min(1, max(0, (age - 0.25) / 0.5)))
    d.text((W / 2, H / 2 + 30), title, font=font(SERIF, 130), fill=WHITE + (a2,), anchor="mm")
    return fr


def title_card(bg, name, sub, age):
    fr = Image.fromarray((np.asarray(bg).astype(np.float32) * 0.5).astype(np.uint8))
    d = ImageDraw.Draw(fr, "RGBA")
    a = int(255 * min(1, age / 0.6))
    d.text((W / 2, H / 2 - 150), "F I R M E N F R I E D H O F", font=font(SANS, 30, 700), fill=(170, 176, 188, a), anchor="mm")
    sc = 1.06 - 0.06 * ease(age / 1.2)
    size = 190 if len(name) <= 10 else int(190 * 10 / len(name))
    d.text((W / 2, H / 2 - 20), name.upper(), font=font(SERIF, int(size * sc)), fill=GOLD + (a,), anchor="mm")
    a2 = int(255 * min(1, max(0, (age - 0.5) / 0.6)))
    d.text((W / 2, H / 2 + 105), sub, font=font(SANS, 48, 500), fill=WHITE + (a2,), anchor="mm")
    d.line([(W / 2 - 260, H / 2 + 165), (W / 2 + 260, H / 2 + 165)], fill=GOLD + (a2,), width=3)
    return fr


def outro_card(age):
    fr = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(fr, "RGBA")
    a = int(255 * min(1, age / 0.6))
    d.text((W / 2, H / 2 - 40), "FIRMENFRIEDHOF", font=font(SERIF, 110), fill=GOLD + (a,), anchor="mm")
    d.text((W / 2, H / 2 + 60), "Jede Woche eine neue Firmengeschichte.", font=font(SANS, 40, 500), fill=WHITE + (a,), anchor="mm")
    return fr


_STATE = {}


def _init(job):
    tl, shots, items, cues, clips, img_dir, windows = build_plan(job)
    _STATE.update(tl=tl, shots=shots, items=items, clips=clips, img_dir=img_dir, windows=windows,
                  vign=build_overlays()[0], grains=build_overlays()[1], sources={})


def find_img(img_dir, sid):
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        q = os.path.join(img_dir, sid + ext)
        if os.path.exists(q):
            return q
    raise FileNotFoundError(sid)


def source_for(si, frame_in_shot):
    S = _STATE
    s = S["shots"][si]
    key = si
    src = S["sources"].get(key)
    if src is None:
        for k_ in [k for k in S["sources"] if k != key]:  # free old ones
            old = S["sources"].pop(k_)
            if isinstance(old, Clip):
                old.close()
        spec = s["spec"]
        if isinstance(spec, dict):
            fn = graphics.GRAPHICS[spec["graphic"]]
            src = ("graphic", fn, spec)
        elif spec in S["clips"]:
            src = Clip(S["clips"][spec], s["t1"] - s["t0"])
            for _ in range(frame_in_shot):  # chunk starts inside this clip: skip ahead
                src.frame(0, "")
        else:
            src = Still(find_img(S["img_dir"], spec))
        S["sources"][key] = src
    return src


def render_frame(fi):
    S = _STATE
    tl, shots, items = S["tl"], S["shots"], S["items"]
    t = fi / FPS
    bars = True
    win = next((w for w in S["windows"] if w[0] <= t < w[1] and w[2] != "pause"), None)
    if t >= tl.total - OUTRO_LEN:
        arr = np.asarray(outro_card(t - (tl.total - OUTRO_LEN))).astype(np.float32)
        bars = False
    elif win and win[2] == "chapter":
        arr = np.asarray(chapter_card(win[3]["n"], win[3]["title"], t - win[0])).astype(np.float32)
        bars = False
    elif win and win[2] == "title":
        if "title_bg" not in S:
            sc = tl.script
            bgid = sc.get("title_bg")
            S["title_bg"] = Still(find_img(S["img_dir"], bgid)).frame(0.5, "push") if bgid else Image.new("RGB", (W, H), NAVY)
        sc = tl.script
        arr = np.asarray(title_card(S["title_bg"], sc.get("company", sc.get("title", "")), sc.get("subtitle", ""), t - win[0])).astype(np.float32)
    else:
        si = next((i for i, x in enumerate(shots) if x["t0"] <= t < x["t1"]), len(shots) - 1)
        s = shots[si]
        p = (t - s["t0"]) / max(0.01, s["t1"] - s["t0"])
        src = source_for(si, int((t - s["t0"]) * FPS))
        if isinstance(src, tuple):
            fr = src[1](p, src[2])
            mood = "none"
        else:
            fr = src.frame(p, s["mode"])
            mood = s["mood"]
        ov = text_layer(items, t)
        if ov is not None:
            fr = fr.convert("RGBA")
            fr.alpha_composite(ov)
            fr = fr.convert("RGB")
        arr = grade(fr, mood)
        WH = 0.16
        if s["whip"] and t - s["t0"] < WH:
            import cv2
            k = 1 - (t - s["t0"]) / WH
            arr = cv2.blur(np.roll(arr, -int(W * 0.25 * k * k), axis=1), (max(1, int(120 * k)), 1))
        nxt = shots[si + 1] if si + 1 < len(shots) else None
        if nxt and nxt["whip"] and s["t1"] - t < WH:
            import cv2
            k = 1 - (s["t1"] - t) / WH
            arr = cv2.blur(np.roll(arr, int(W * 0.25 * k * k), axis=1), (max(1, int(120 * k)), 1))
    arr = arr * S["vign"] + S["grains"][fi % len(S["grains"])]
    if t < LEAD_IN:
        arr *= ease(t / LEAD_IN)
    for w0, w1, kind, _ in S["windows"]:
        if kind == "title" and 0 <= t - w0 < 0.5:
            arr = arr + np.array([255, 170, 80]) * 0.30 * (1 - (t - w0) / 0.5)
        if kind in ("chapter", "title") and (w0 - 0.12 <= t < w0 or w1 - 0.1 <= t < w1):
            arr *= 0.25
    if t > tl.total - 1.0:
        arr *= max(0.0, (tl.total - t) / 1.0)
    if bars:
        arr[:BAR] = 0
        arr[H - BAR:] = 0
    return arr.clip(0, 255).astype(np.uint8)


def render_chunk(args):
    job, f0, f1, path = args
    if not _STATE:
        _init(job)
    tmp = path + ".part.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                            "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p", "-g", "60", tmp],
                           stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        enc.stdin.write(render_frame(fi).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("encoder failed for " + path)
    os.replace(tmp, path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--until", type=float, default=None, help="render only the first N seconds (preview)")
    a = ap.parse_args()
    job = os.path.abspath(a.job)
    tl, shots, items, cues, clips, img_dir, windows = build_plan(job)
    total = min(tl.total, a.until) if a.until else tl.total
    print(f"episode {total:.1f}s, {len(shots)} shots, {len(items)} overlays, {len(clips)} clips", flush=True)
    # depth maps once, before the workers fork
    for s in shots:
        if isinstance(s["spec"], str) and s["spec"] not in clips:
            depth_map(find_img(img_dir, s["spec"]), (8, 8))
    work = os.path.join(job, "render")
    os.makedirs(work, exist_ok=True)
    wav = os.path.join(work, "mix.wav")
    build_audio(job, tl, cues, windows, wav)
    nframes = int(total * FPS)
    # cut chunks at shot starts so no clip is split badly; ~20 s per chunk
    bounds = [0]
    for s in shots:
        f = int(s["t0"] * FPS)
        if f - bounds[-1] >= 20 * FPS and f < nframes:
            bounds.append(f)
    bounds.append(nframes)
    tasks = [(job, b0, b1, os.path.join(work, f"chunk_{i:04d}.mp4")) for i, (b0, b1) in enumerate(zip(bounds, bounds[1:]))]
    todo = [t for t in tasks if not os.path.exists(t[3])]
    print(f"{len(tasks)} chunks, {len(todo)} to render on {a.workers} workers", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(a.workers) as pool:
        for i, path in enumerate(pool.imap_unordered(render_chunk, todo)):
            print(f"chunk {i + 1}/{len(todo)} done", flush=True)
    lst = os.path.join(work, "chunks.txt")
    with open(lst, "w") as f:
        for t in tasks:
            f.write(f"file '{t[3]}'\n")
    joined = os.path.join(work, "video.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined], check=True)
    tmp = a.out + ".part.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp], check=True)
    os.replace(tmp, a.out)
    json.dump({"total": total, "shots": [dict(t0=s["t0"], t1=s["t1"], spec=s["spec"] if isinstance(s["spec"], str) else s["spec"]["graphic"]) for s in shots],
               "chapters": [dict(t=w[0], n=w[3]["n"], title=w[3]["title"]) for w in windows if w[2] == "chapter"],
               "lines": [dict(id=l["id"], t0=tl.T(l["start"]), t1=tl.T(l["end"])) for l in tl.lines]},
              open(os.path.join(job, "render_map.json"), "w"), indent=1)
    print("done", a.out, round(total, 1), "s")


if __name__ == "__main__":
    main()
