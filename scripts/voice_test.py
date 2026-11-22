"""Voice test: find German male narrator voices in the ElevenLabs library,
narrate the test script with the best candidates, save audio + word timings."""
import base64, json, os, sys, urllib.request, urllib.parse, urllib.error

KEY = os.environ["ELEVENLABS_API_KEY"]
API = "https://api.elevenlabs.io"
OUT = "test/out"
os.makedirs(OUT, exist_ok=True)

def call(method, path, body=None, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:500]}

script = json.load(open("test/script_wirecard_test.json"))
text = "\n\n".join(l["text"] for l in script["lines"])

user = call("GET", "/v1/user/subscription")
print("subscription:", {k: user.get(k) for k in ("tier", "character_count", "character_limit")})

found = call("GET", "/v1/shared-voices", params={
    "language": "de", "gender": "male", "use_cases": "narrative_story",
    "page_size": 30, "sort": "usage_character_count_1y"})
voices = found.get("voices", []) if isinstance(found, dict) else []
if not voices:
    found = call("GET", "/v1/shared-voices", params={"language": "de", "gender": "male", "page_size": 30})
    voices = found.get("voices", []) if isinstance(found, dict) else []
summary = [{k: v.get(k) for k in ("voice_id", "public_owner_id", "name", "accent", "age", "descriptive",
                                    "use_case", "category", "usage_character_count_1y", "description")}
           for v in voices]
json.dump(summary, open(f"{OUT}/voice_candidates.json", "w"), ensure_ascii=False, indent=1)
print("candidates:", len(summary))

# prefer deep / calm / documentary descriptions, older narrators
def score(v):
    d = " ".join(str(v.get(k) or "") for k in ("descriptive", "description", "use_case", "age")).lower()
    s = (v.get("usage_character_count_1y") or 0) / 1e6
    for w, b in (("deep", 30), ("calm", 20), ("documentar", 40), ("narrat", 20), ("serious", 15),
                 ("authorit", 15), ("middle", 10), ("old", 5), ("warm", 5)):
        if w in d: s += b
    for w, b in (("young", -15), ("energetic", -15), ("social", -10), ("conversational", -5)):
        if w in d: s += b
    return s
picked = sorted(voices, key=score, reverse=True)[:int(os.environ.get("N_VOICES", "3"))]

settings = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True, "speed": 0.95}
results = []
for i, v in enumerate(picked, 1):
    vid = v["voice_id"]
    body = {"text": text, "model_id": "eleven_multilingual_v2", "language_code": "de", "voice_settings": settings}
    r = call("POST", f"/v1/text-to-speech/{vid}/with-timestamps", body)
    if "_error" in r:  # shared voices may need adding to the library first
        add = call("POST", f"/v1/voices/add/{v['public_owner_id']}/{vid}", {"new_name": f"FF-{v['name']}"[:40]})
        vid = add.get("voice_id", vid)
        r = call("POST", f"/v1/text-to-speech/{vid}/with-timestamps", body)
    if "_error" in r:
        print("FAILED", v["name"], r); results.append({"name": v["name"], "error": r}); continue
    open(f"{OUT}/voice_{i}.mp3", "wb").write(base64.b64decode(r["audio_base64"]))
    json.dump(r.get("alignment"), open(f"{OUT}/voice_{i}_alignment.json", "w"))
    results.append({"n": i, "name": v["name"], "voice_id": vid, "descriptive": v.get("descriptive"),
                    "age": v.get("age"), "accent": v.get("accent")})
    print("OK", i, v["name"])
json.dump({"settings": settings, "results": results}, open(f"{OUT}/voice_results.json", "w"), ensure_ascii=False, indent=1)
if not any("n" in r for r in results):
    sys.exit("no voice succeeded")
