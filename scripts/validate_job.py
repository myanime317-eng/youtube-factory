"""Checks a job folder before it is committed. Exit code 1 with a list of problems if anything is wrong.
Usage: python3 scripts/validate_job.py jobs/<slug>
"""
import json, os, sys

job = sys.argv[1]
errs, warn = [], []
sc = json.load(open(os.path.join(job, "script.json")))
ip = json.load(open(os.path.join(job, "image_prompts.json")))
ids = {s["id"] for s in ip["shots"]}
slug = os.path.basename(os.path.normpath(job))
if ip.get("flow_out") != f"jobs/{slug}/flow_img":
    errs.append(f'image_prompts.json flow_out must be "jobs/{slug}/flow_img"')
graphics = {"chart", "map", "timeline", "quote", "card", "text"}
kinds = {"date", "counter", "big", "list", "lower"}
music = {"intro", "rise", "tension", "collapse", "reflective", "dark"}
moods = {"calm", "rise", "tension", "shock", "reveal", "reflective", "title"}
seen, words, chapters, titles = set(), 0, 0, 0
for l in sc["lines"]:
    lid = l.get("id")
    if lid in seen:
        errs.append(f"duplicate line id {lid}")
    seen.add(lid)
    t = l.get("text", "")
    words += len(t.split())
    if any(ch.isdigit() for ch in t):
        errs.append(f"{lid}: write numbers as words for the narrator: {t[:60]}")
    if l.get("mood") not in moods:
        errs.append(f"{lid}: mood must be one of {sorted(moods)}")
    if l.get("music") and l["music"] not in music:
        errs.append(f"{lid}: music must be one of {sorted(music)}")
    chapters += bool(l.get("chapter"))
    titles += bool(l.get("title_card"))
    if not l.get("shots"):
        errs.append(f"{lid}: no shots")
    for s in l.get("shots", []):
        if isinstance(s, dict):
            if s.get("graphic") not in graphics:
                errs.append(f"{lid}: unknown graphic {s}")
        elif s not in ids:
            errs.append(f"{lid}: shot {s} has no image prompt")
    for o in l.get("overlays", []):
        if o.get("kind") not in kinds:
            errs.append(f"{lid}: unknown overlay kind {o.get('kind')}")
        if o.get("at") and o["at"].lower() not in t.lower():
            errs.append(f"{lid}: overlay anchor '{o['at']}' is not in the line text")
    for s in l.get("sfx", []):
        if s.get("at") and s["at"].lower() not in t.lower():
            errs.append(f"{lid}: sfx anchor '{s['at']}' is not in the line text")
if titles != 1:
    errs.append("exactly one line needs \"title_card\": true (end of the cold open)")
if chapters < 3:
    warn.append(f"only {chapters} chapters")
if not 1500 <= words <= 2600:
    warn.append(f"{words} words (target 1,800-2,200)")
for k in ("company", "subtitle", "title_bg", "youtube", "thumbnail", "shorts", "schedule", "sources"):
    if k not in sc:
        errs.append(f"script.json is missing \"{k}\"")
th = sc.get("thumbnail", {})
if th.get("bg") and th["bg"] not in ids:
    errs.append(f"thumbnail bg {th['bg']} has no image prompt")
if sc.get("title_bg") and sc["title_bg"] not in ids:
    errs.append("title_bg has no image prompt")
line_ids = [l["id"] for l in sc["lines"]]
for s in sc.get("shorts", []):
    if s.get("from") not in line_ids or s.get("to") not in line_ids:
        errs.append(f"short {s.get('id')}: from/to must be line ids")
print(f"{len(sc['lines'])} lines, {words} words, {len(ids)} images, {chapters} chapters")
for w in warn:
    print("WARN", w)
for e in errs:
    print("ERROR", e)
sys.exit(1 if errs else 0)
