"""Vertical Shorts (1080x1920) cut from a rendered episode, with a hook title and word-by-word captions.

script.json -> "shorts": [{"id": "short1", "from": "l05", "to": "l12", "hook": "WO SIND 1,9 MILLIARDEN?",
                           "title": "...", "description": "...", "tags": [...]}]
Usage: python3 editor/make_shorts.py jobs/<slug> episode.mp4 out_dir
"""
import json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_episode import Timeline  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.path.dirname(HERE), "assets", "fonts")
HEAVY = os.path.join(FONTS, "Montserrat[wght].ttf")
VW, VH = 1080, 1920


def heavy(size):
    f = ImageFont.truetype(HEAVY, size)
    try:
        f.set_variation_by_axes([900])
    except Exception:
        pass
    return f


def hook_png(text, path):
    """Hook title at the top: white heavy capitals on black boxes, last word in red."""
    img = Image.new("RGBA", (VW, 520), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    words = text.upper().split()
    f = heavy(78)
    lines, cur = [], ""
    for w in words:
        if f.getlength((cur + " " + w).strip()) > VW - 160 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = 150
    for li, line in enumerate(lines):
        wl = f.getlength(line)
        x = (VW - wl) / 2
        bb = f.getbbox(line)
        d.rectangle([x - 22, y - 10, x + wl + 22, y + (bb[3] - bb[1]) + 22], fill=(0, 0, 0, 255))
        cx = x
        parts = line.split(" ")
        for pi, w in enumerate(parts):
            last = li == len(lines) - 1 and pi == len(parts) - 1
            d.text((cx, y - bb[1] + 6), w, font=f, fill=(232, 30, 36) if last else (255, 255, 255))
            cx += f.getlength(w + " ")
        y += (bb[3] - bb[1]) + 40
    img.save(path)


def ass_time(t):
    h, r = divmod(max(0.0, t), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def captions_ass(words, path):
    """Two or three words at a time, the spoken word in yellow; big, with a black outline."""
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Cap,Anton,132,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or w[0].endswith((".", ",", "?", "!", ":")):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    for g in groups:
        for k, (txt, t0, t1) in enumerate(g):
            end = g[k + 1][1] if k + 1 < len(g) else t1 + 0.12
            parts = [("{\\c&H00D6FF&}" + x[0].upper() + "{\\c&HFFFFFF&}") if j == k else x[0].upper() for j, x in enumerate(g)]
            ev.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(end)},Cap,,0,0,0,,{{\\pos(540,1420)}}" + " ".join(parts))
    open(path, "w").write(head + "\n".join(ev) + "\n")


def main(job, episode, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    tl = Timeline(job)
    sc = tl.script
    ids = [l["id"] for l in tl.lines]
    made = []
    for sh in sc.get("shorts", []):
        a, b = ids.index(sh["from"]), ids.index(sh["to"])
        la, lb = tl.lines[a], tl.lines[b]
        t0 = max(0.0, tl.T(la["start"]) - 0.25)
        t1 = tl.T(lb["end"]) + 0.6
        if t1 - t0 > 58:
            t1 = t0 + 58
        words = []
        for l in tl.lines[a:b + 1]:
            seg = tl.text[l["i"]: l["j"] + 1]
            pos = 0
            for w in seg.split():
                k = seg.index(w, pos)
                pos = k + len(w)
                gi = l["i"] + k
                ws, we = tl.T(tl.st[gi]) - t0, tl.T(tl.en[gi + len(w) - 1]) - t0
                if 0 <= ws < t1 - t0:
                    words.append((w, ws, we))
        work = os.path.join(out_dir, sh["id"])
        os.makedirs(work, exist_ok=True)
        hook_png(sh["hook"], os.path.join(work, "hook.png"))
        captions_ass(words, os.path.join(work, "cap.ass"))
        out = os.path.join(out_dir, sh["id"] + ".mp4")
        # inside the letterbox: 1920x818; foreground keeps the middle 1360 px, background is a blurred fill
        vf = (f"[0:v]crop=1920:818:0:131,split[a][b];"
              f"[a]scale=-2:1920,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.12[bg];"
              f"[b]crop=1360:818:280:0,scale=1080:-2[fg];"
              f"[bg][fg]overlay=0:(H-h)/2-60[v1];[v1][1:v]overlay=0:0[v2];"
              f"[v2]subtitles={os.path.join(work, 'cap.ass')}:fontsdir={FONTS},fade=t=out:st={t1 - t0 - 0.4:.2f}:d=0.4[v]")
        tmp = out + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}", "-i", episode,
                        "-i", os.path.join(work, "hook.png"), "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
                        "-af", f"afade=t=out:st={t1 - t0 - 0.4:.2f}:d=0.4", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "20", "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", tmp], check=True)
        os.replace(tmp, out)
        made.append({"id": sh["id"], "file": out, "title": sh.get("title", sh["hook"]), "seconds": round(t1 - t0, 1)})
        print("short", sh["id"], round(t1 - t0, 1), "s")
    json.dump(made, open(os.path.join(out_dir, "shorts.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
