# v3: new Creator key
"""Build the channel's sound kit with ElevenLabs: sound effects and (if the plan allows) a music bed.

Writes assets/sound/<name>.mp3 and assets/sound/report.json. Existing files are kept, so it only
spends credits on what is missing.
"""
import json, os, urllib.error, urllib.request

KEY = os.environ["ELEVENLABS_API_KEY"]
OUT = "assets/sound"
os.makedirs(OUT, exist_ok=True)
report = {}

SFX = {
    "whoosh_1": ("Fast cinematic whoosh transition, airy, clean, no music", 1.2),
    "whoosh_2": ("Deep heavy cinematic swoosh pass-by transition with low end", 1.5),
    "impact_1": ("Massive cinematic trailer impact hit, deep sub bass boom with long dark reverb tail", 4.0),
    "impact_2": ("Short punchy cinematic hit, tight low thud, documentary accent", 2.0),
    "riser_1": ("Tense cinematic riser building up to a hit, dark synth and strings, ends abruptly", 4.0),
    "braam_1": ("Dark cinematic braam, huge low brass horn blast, ominous", 4.0),
    "typing_1": ("Old typewriter typing a few keys quickly, close mic, dry", 1.5),
    "camera_1": ("Several press camera shutter clicks and flashes, paparazzi", 2.0),
    "paper_1": ("Newspaper being slapped down on a wooden table, paper rustle", 1.5),
    "heartbeat_1": ("Slow tense heartbeat pulse, low and muffled, suspense", 5.0),
    "cash_1": ("Stacks of banknotes riffling and counting machine, money", 2.0),
    "siren_1": ("Distant police siren at dawn, muffled through rain", 5.0),
    "jet_1": ("Private jet taking off and roaring past, rain on runway", 5.0),
    "glitch_1": ("Short digital glitch and stock ticker data crash sound", 1.5),
}
MUSIC = {
    "music_dark_1": "Dark cinematic documentary underscore, slow pulsing low synth, sparse piano notes, tense strings, "
                    "investigative mood like a true-crime business documentary, no drums at the start, builds slowly, instrumental",
    "music_rise_1": "Uplifting yet suspicious corporate success music, steady modern pulse, warm synths, subtle tension underneath, "
                    "for a company's meteoric rise in a business documentary, instrumental",
}


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


for name, (prompt, dur) in SFX.items():
    path = f"{OUT}/{name}.mp3"
    if os.path.exists(path):
        report[name] = "kept"
        continue
    try:
        audio = post("https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_192",
                     {"text": prompt, "duration_seconds": dur, "prompt_influence": 0.5})
        open(path, "wb").write(audio)
        report[name] = f"ok {len(audio)}"
    except urllib.error.HTTPError as e:
        report[name] = f"HTTP {e.code} {e.read().decode(errors='ignore')[:300]}"
    print(name, report[name], flush=True)

for name, prompt in MUSIC.items():
    path = f"{OUT}/{name}.mp3"
    if os.path.exists(path):
        report[name] = "kept"
        continue
    try:
        audio = post("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192",
                     {"prompt": prompt, "music_length_ms": 75000, "force_instrumental": True})
        open(path, "wb").write(audio)
        report[name] = f"ok {len(audio)}"
    except urllib.error.HTTPError as e:
        report[name] = f"HTTP {e.code} {e.read().decode(errors='ignore')[:300]}"
    print(name, report[name], flush=True)

json.dump(report, open(f"{OUT}/report.json", "w"), indent=1)
