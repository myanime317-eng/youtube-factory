"""Produce one episode end to end on GitHub: voice -> video -> Shorts -> thumbnail -> release -> upload queue.

Runs when jobs/<slug>/flow_img/DONE appears (the laptop helper finished the images).
Usage: python3 scripts/produce.py jobs/<slug>
"""
import datetime as dt, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("GITHUB_REPOSITORY", "myanime317-eng/youtube-factory")
VOICE = os.environ.get("FF_VOICE_ID", "kkJxCnlRCckmfFvzDW5Q")  # Alexander - Deep TV Narrator
AI_NOTE = ("Hinweis: Bilder, Grafiken und Sprecherstimme dieses Videos sind KI-gestützt erstellt. "
           "Die Fakten sind recherchiert; Quellen siehe unten.")


def run(*a):
    print("+", " ".join(a), flush=True)
    subprocess.run(a, check=True, cwd=ROOT)


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def main(job):
    job = os.path.abspath(job)
    slug = os.path.basename(job)
    sc = json.load(open(os.path.join(job, "script.json")))
    out = os.path.join(job, "out")
    os.makedirs(out, exist_ok=True)

    if not os.path.exists(os.path.join(job, "voice_alignment.json")):
        run("python3", "scripts/voice_v3.py", os.path.join(job, "script.json"), VOICE, os.path.join(job, "voice"))
    episode = os.path.join(out, "episode.mp4")
    if not os.path.exists(episode):
        run("python3", "editor/render_episode.py", job, episode, "--workers", str(os.cpu_count() or 2))
    if sc.get("shorts"):
        run("python3", "editor/make_shorts.py", job, episode, os.path.join(out, "shorts"))
    thumb = os.path.join(out, "thumb.jpg")
    th = dict(sc["thumbnail"])
    for key in ("bg", "inset"):
        if th.get(key) and not os.path.exists(th[key]):
            for ext in (".png", ".jpg"):
                p = os.path.join(job, "flow_img", th[key] + ext)
                if os.path.exists(p):
                    th[key] = p
    sys.path.insert(0, os.path.join(ROOT, "editor"))
    import thumbnail
    thumbnail.make(th, thumb)
    if os.path.getsize(thumb) > 1_900_000:  # YouTube limit is 2 MB
        from PIL import Image
        Image.open(thumb).save(thumb, "JPEG", quality=80, optimize=True)

    # description: hook, chapters (from the real render), sources, AI note
    rm = json.load(open(os.path.join(job, "render_map.json")))
    yt = sc["youtube"]
    chapters = ["0:00 Intro"] + [f"{stamp(c['t'])} {c['title']}" for c in rm["chapters"]]
    desc = (yt["description"].strip() + "\n\n" + "\n".join(chapters) + "\n\n"
            + ("Quellen:\n" + "\n".join("• " + s for s in sc.get("sources", [])) + "\n\n" if sc.get("sources") else "")
            + AI_NOTE + "\n\n" + " ".join("#" + h for h in yt.get("hashtags", ["Firmenfriedhof", "Wirtschaftsdoku"])))

    tag = f"ep-{slug}"
    files = [episode, thumb]
    shorts = []
    sj = os.path.join(out, "shorts", "shorts.json")
    if os.path.exists(sj):
        shorts = json.load(open(sj))
        files += [s["file"] for s in shorts]
    try:
        run("gh", "release", "view", tag, "-R", REPO)
    except subprocess.CalledProcessError:
        run("gh", "release", "create", tag, "-R", REPO, "--title", yt["title"][:100], "--notes", "Firmenfriedhof episode")
    run("gh", "release", "upload", tag, *files, "-R", REPO, "--clobber")
    base = f"https://github.com/{REPO}/releases/download/{tag}/"

    sched = sc.get("schedule", {})
    now = dt.datetime.now(dt.timezone.utc)
    ep_at = sched.get("episode") or (now + dt.timedelta(hours=1)).isoformat()
    q = [{"id": f"{slug}-episode", "at": ep_at, "title": yt["title"], "description": desc, "tags": yt.get("tags", []),
          "asset_url": base + "episode.mp4", "thumb_url": base + "thumb.jpg"}]
    spec = {s["id"]: s for s in sc.get("shorts", [])}
    for n, s in enumerate(shorts):
        meta = spec.get(s["id"], {})
        at = (sched.get("shorts") or [])[n] if n < len(sched.get("shorts") or []) else \
            (dt.datetime.fromisoformat(ep_at.replace("Z", "+00:00")) + dt.timedelta(days=n + 1)).isoformat()
        q.append({"id": f"{slug}-{s['id']}", "at": at, "title": meta.get("title", s["title"])[:100],
                  "description": (meta.get("description", "") + "\n\nGanze Doku auf dem Kanal: Firmenfriedhof\n\n"
                                  + AI_NOTE + "\n\n#Shorts #Firmenfriedhof").strip(),
                  "tags": meta.get("tags", yt.get("tags", [])), "asset_url": base + os.path.basename(s["file"])})
    qp = os.path.join(ROOT, "publish", "queue.json")
    queue = json.load(open(qp)) if os.path.exists(qp) else []
    have = {x["id"] for x in queue}
    queue += [x for x in q if x["id"] not in have]
    json.dump(queue, open(qp, "w"), ensure_ascii=False, indent=1)
    json.dump({"produced": now.isoformat(), "release": tag, "episode_seconds": rm["total"], "queued": [x["id"] for x in q]},
              open(os.path.join(job, "produced.json"), "w"), indent=1)
    print("queued", len(q), "uploads")


if __name__ == "__main__":
    main(sys.argv[1])
