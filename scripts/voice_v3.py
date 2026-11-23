"""Narration with ElevenLabs v3 audio tags (emotion), then forced alignment for exact word timing.

Reads a script JSON whose lines may carry "tags" (e.g. "[serious]"); tags are spoken as performance cues
but are not part of the text the editor aligns to.
Writes <out>.mp3 and <out>_alignment.json in the same character-alignment format as voice_test.py.
Usage: python3 scripts/voice_v3.py <script.json> <voice_id> <out_stem>
"""
import json, os, sys, urllib.error, urllib.request, uuid

KEY = os.environ["ELEVENLABS_API_KEY"]
script_path, voice_id, out = sys.argv[1], sys.argv[2], sys.argv[3]
script = json.load(open(script_path))
lines = script["lines"]
plain = "\n\n".join(l["text"] for l in lines)
tagged = "\n\n".join((l.get("tags", "") + " " + l["text"]).strip() for l in lines)


def post_json(path, body):
    req = urllib.request.Request("https://api.elevenlabs.io" + path, data=json.dumps(body).encode(),
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


# Eleven v3 takes a limited amount of text per request: narrate in parts of whole lines, then join.
LIMIT = 2400
parts, cur = [], []
for l in lines:
    t = (l.get("tags", "") + " " + l["text"]).strip()
    if cur and sum(len(x) + 2 for x in cur) + len(t) > LIMIT:
        parts.append(cur)
        cur = []
    cur.append(t)
if cur:
    parts.append(cur)
import subprocess, tempfile
tmpd = tempfile.mkdtemp()
files = []
for n, p in enumerate(parts):
    a = post_json(f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_192", {
        "text": "\n\n".join(p), "model_id": "eleven_v3", "language_code": "de",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "use_speaker_boost": True},
    })
    f = os.path.join(tmpd, f"p{n:03d}.mp3")
    open(f, "wb").write(a)
    files.append(f)
    print("tts part", n + 1, "/", len(parts), len(a), flush=True)
lst = os.path.join(tmpd, "l.txt")
open(lst, "w").write("".join(f"file '{f}'\n" for f in files))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-af", "apad=pad_dur=0.0",
                "-c:a", "libmp3lame", "-b:a", "192k", out + ".mp3"], check=True)
audio = open(out + ".mp3", "rb").read()
print("tts ok", len(audio))

# forced alignment: multipart upload of the audio + the plain text
boundary = uuid.uuid4().hex
body = b"".join([
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n".encode(),
    audio, b"\r\n",
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n".encode(), plain.encode(), b"\r\n",
    f"--{boundary}--\r\n".encode(),
])
req = urllib.request.Request("https://api.elevenlabs.io/v1/forced-alignment", data=body,
                             headers={"xi-api-key": KEY, "Content-Type": f"multipart/form-data; boundary={boundary}"})
try:
    fa = json.loads(urllib.request.urlopen(req, timeout=600).read())
except urllib.error.HTTPError as e:
    sys.exit(f"alignment failed: HTTP {e.code} {e.read()[:300]}")

chars = fa["characters"]
got = "".join(c["text"] for c in chars)
# map the aligner's characters onto the exact script text the editor expects
starts, ends, j = [], [], 0
for ch in plain:
    while j < len(chars) and chars[j]["text"] != ch and ch not in "\n":
        j += 1
    if ch == "\n" or j >= len(chars):
        prev = ends[-1] if ends else 0.0
        starts.append(prev)
        ends.append(prev)
        continue
    starts.append(chars[j]["start"])
    ends.append(chars[j]["end"])
    j += 1
json.dump({"characters": list(plain), "character_start_times_seconds": starts,
           "character_end_times_seconds": ends}, open(out + "_alignment.json", "w"))
print("aligned", len(plain), "chars; aligner text matched:", got.replace("\n", "") == plain.replace("\n", ""))
