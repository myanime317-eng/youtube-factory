"""Make the shot images for a video.

Tries Google Gemini image models first (GEMINI_API_KEY), then falls back to
the free Pollinations FLUX service. Writes <out_dir>/sNN.<ext> and a log.
Usage: python3 scripts/make_images.py test/image_prompts.json test/img
"""
import base64, json, os, sys, time, urllib.parse, urllib.request, urllib.error

PROMPTS, OUT = sys.argv[1], sys.argv[2]
KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = ["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview",
                 "gemini-2.0-flash-preview-image-generation"]
os.makedirs(OUT, exist_ok=True)
log = {"shots": {}, "errors": []}


def http(url, data=None, headers=None, timeout=180):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def gemini(prompt):
    if not KEY:
        return None
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                                 "imageConfig": {"aspectRatio": "16:9"}}}
    for m in list(GEMINI_MODELS):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        b = body
        if "2.0" in m:  # older model has no imageConfig
            b = {"contents": body["contents"],
                 "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        try:
            raw, _ = http(url, json.dumps(b).encode(),
                          {"Content-Type": "application/json", "x-goog-api-key": KEY})
            res = json.loads(raw)
            for c in res.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    d = p.get("inlineData") or p.get("inline_data")
                    if d and d.get("data"):
                        ext = "png" if "png" in d.get("mimeType", d.get("mime_type", "")) else "jpg"
                        return base64.b64decode(d["data"]), ext, m
            log["errors"].append(f"{m}: no image in response")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:300]
            log["errors"].append(f"{m}: HTTP {e.code} {msg}")
            if e.code in (400, 403, 404, 429):
                GEMINI_MODELS.remove(m)  # don't retry a model that refuses us
        except Exception as e:
            log["errors"].append(f"{m}: {e}")
    return None


def pollinations(prompt, seed):
    q = urllib.parse.quote(prompt)
    url = (f"https://image.pollinations.ai/prompt/{q}?width=1920&height=1088"
           f"&model=flux&nologo=true&enhance=false&seed={seed}")
    for attempt in range(4):
        try:
            raw, ct = http(url, timeout=240)
            if len(raw) > 20000:
                return raw, ("png" if "png" in ct else "jpg"), "pollinations-flux"
            log["errors"].append(f"pollinations small response {len(raw)}")
        except Exception as e:
            log["errors"].append(f"pollinations try {attempt}: {e}")
        time.sleep(8 * (attempt + 1))
    return None


spec = json.load(open(PROMPTS))
style = spec["style"]
for i, shot in enumerate(spec["shots"]):
    prompt = f"{shot['prompt']}. {style}. Wide 16:9 frame."
    got = gemini(prompt) or pollinations(prompt, 1000 + i)
    if not got:
        log["shots"][shot["id"]] = "FAILED"
        print(shot["id"], "FAILED", flush=True)
        continue
    data, ext, src = got
    with open(os.path.join(OUT, f"{shot['id']}.{ext}"), "wb") as f:
        f.write(data)
    log["shots"][shot["id"]] = src
    print(shot["id"], src, len(data), flush=True)
    time.sleep(2)

json.dump(log, open(os.path.join(OUT, "log.json"), "w"), indent=1)
