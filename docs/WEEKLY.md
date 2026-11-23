# Firmenfriedhof – weekly episode instructions (for the Sunday Claude session)

Channel: **Firmenfriedhof** (@derfirmenfriedhof), German business rise-and-fall documentaries, Magnates-Media style.
Audience: German-speaking (DE/AT/CH). Voice: Alexander (ElevenLabs v3, emotion tags). Everything in German except image prompts (English).

## What to do each week
1. `git pull`. Pick the next topic from `docs/topics.md` that has no folder in `jobs/` yet (first unchecked line). Mark it `[x]`.
2. Research it properly with web search (8–15 searches): founding, rise, peak numbers, key people (roles only), turning point, collapse, aftermath, lessons. Use reputable sources (Spiegel, Handelsblatt, FAZ, SZ, Zeit, tagesschau, manager magazin, FT, Reuters, Bundestag/court documents). Every number must be sourced. Never invent quotes; paraphrase instead and mark "sinngemäß".
3. Write `jobs/<slug>/script.json`, `jobs/<slug>/image_prompts.json` and optionally `jobs/<slug>/clip_prompts.json` (format below). `<slug>` = lowercase company, e.g. `schlecker`.
4. Run `python3 scripts/validate_job.py jobs/<slug>` until it prints no ERROR lines.
5. Commit and push. The laptop helper makes the images in Google Flow (free); when they are done, GitHub produces voice, video, 5 Shorts and the thumbnail and queues them; Zapier uploads at the scheduled times.
6. Keep it efficient: research once, write once, no test renders.

## Story rules (Magnates style)
- 1,300–1,700 words → 12–15 minutes (Eleven v3 with tags speaks ~100 words per minute). Short sentences. Du-form is not used; neutral narrator, but vivid.
- **Cold open (45–60 s):** start at the most dramatic moment (peak or crash), the big number, the question. Ends with a line like "Das ist die Geschichte von X." → that line gets `"title_card": true`.
- Then 4–6 chapters (`"chapter": {"n": 1, "title": "Der Aufstieg"}` on the first line of each). Typical: Anfänge → Aufstieg → Warnsignale → Absturz → Danach/Lehren.
- Open loops ("Doch das war erst der Anfang."), concrete details, numbers, dates; a 1-second `"pause_before": 1.0` before 2–4 big reveals.
- Last chapter: what remains today and one clear lesson. End with a calm closing line.
- **Numbers and dates in `text` are written as words** (the narrator reads text; the validator rejects digits). Overlays show digits.
- Tags (`"tags"`): one per line from [calm], [serious], [curious], [impressed], [dramatic], [whispers], [slowly], [ominous], [sad], [surprised]. Use [whispers] rarely.
- Moods: calm, rise, tension, shock, reveal, reflective (they set colour grade and camera move).
- Music (`"music"` on the line where it changes): intro (cold open), rise, tension, collapse, reflective, dark. 5–8 changes per episode.

## Pictures
- About one shot every 3 seconds: 1–4 shots per line, ~200–240 image shots per episode plus 12–20 graphics.
- Image prompt rules: cinematic documentary stills; no logos or real brand marks unless essential text like a headline; **no real people's faces** (only from behind, silhouettes, hands, crowds); German settings (cities, offices, Autobahn, Plattenbau, Fußgängerzone) where it fits; text inside the image is allowed for headlines, signs, documents ("WIRECARD PLEITE").
- Vary shot types: aerial, wide, close-up, detail, hands, documents, screens, symbolic (empty vault, crumbling sign).
- Graphics (inline in `shots`, use them for every key number/place/person):
  - `{"graphic":"chart","label":"Aktienkurs X (EUR)","mode":"rise|crash|full","points":[["2014",31],["",36],...],"peak":10,"peak_label":"SEP 2018","drop_label":"−99 %","unit":"€"}`
  - `{"graphic":"map","from":[lon,lat,"MÜNCHEN"],"to":[lon,lat,"MANILA"],"highlight":["DEU","PHL"],"caption":"..."}` (ISO-3 codes)
  - `{"graphic":"timeline","events":[["1999","Gründung"],...],"focus":3,"focus_red":true}`
  - `{"graphic":"card","name":"…","role":"…","note":"…","status":"red|gold"}` (silhouette, never a face)
  - `{"graphic":"quote","text":"…","by":"…"}` (only real, sourced quotes; else paraphrase)
  - `{"graphic":"text","title":"…","sub":"…","red":true}`
- Overlays on pictures (anchor `at` = a word that appears in that line's text):
  - `{"kind":"date","text":"SEPTEMBER 2018","at":"September"}`
  - `{"kind":"counter","to":24.6,"unit":"MRD. €","label":"Börsenwert","at":"Milliarden","decimals":1}`
  - `{"kind":"big","text":"PLEITE","at":"pleite","color":"red|gold|white","sub":"…"}`
  - `{"kind":"list","names":["SIEMENS","VW","WIRECARD"],"hl":"WIRECARD","at":"neben"}`
- Sound effects: `{"name":"impact_1|impact_2|braam_1|whoosh_1|whoosh_2|riser_1|typing_1|camera_1|paper_1|heartbeat_1|cash_1|siren_1|jet_1|glitch_1","at":"word"}` — 15–30 per episode, on reveals and numbers.

## script.json
```json
{"company":"Wirecard","subtitle":"Die Firma, die es nie gab","title_bg":"s240",
 "lines":[{"id":"l001","text":"…","tags":"[calm]","mood":"calm","music":"intro","shots":["s001","s002"],
           "overlays":[…],"sfx":[…]}, … ],
 "youtube":{"title":"Wirecard: Wie Deutschlands größter Betrug alle täuschte","description":"2–3 Sätze Hook + Kontext (mit Keywords).",
            "tags":["Wirecard","Wirecard Skandal","Markus Braun","Jan Marsalek","Wirtschaftsdoku","Firmenfriedhof"],"hashtags":["Wirecard","Doku","Firmenfriedhof"]},
 "thumbnail":{"bg":"thumb","lines":["1,9 MILLIARDEN","EINFACH WEG?"],"accent":"WEG?","accent_color":"red|yellow","inset":"s120","text_pos":"bottom_left|top_left"},
 "shorts":[{"id":"short1","from":"l005","to":"l014","hook":"WO SIND 1,9 MILLIARDEN?","title":"… #shorts","description":"…","tags":[…]}, … 5 total, each 30–58 s, self-contained, strongest moments],
 "schedule":{"episode":"<next Thursday>T16:00:00Z","shorts":["<Fri>T16:00:00Z","<Sat>…","<Sun>…","<Mon>…","<Tue>…"]},
 "sources":["Titel – Medium, Datum, URL", …]}
```
Title rules: 45–70 characters, company name first, curiosity + keyword ("Aufstieg und Fall", "Skandal", "Pleite", "Wie … "). Thumbnail text: 2–4 words, never repeats the title.

## image_prompts.json
```json
{"flow_out":"jobs/<slug>/flow_img","flow_project":"Firmenfriedhof_<Slug>","aspect_ratio":"16:9",
 "style":"Cinematic documentary film still, shot on 35mm anamorphic lens, shallow depth of field, dramatic low-key lighting, rich deep shadows, teal and amber color grade, subtle film grain, photorealistic, ultra detailed, no logos, no watermark",
 "shots":[{"id":"s001","line":"l001","prompt":"…"}, …,
          {"id":"thumb","line":"l001","prompt":"YouTube thumbnail background in the style of RealLifeLore: <scene>, the <subject> highlighted in solid translucent red with a thick white outline, a thick white curved arrow pointing at it, bright saturated colors, high contrast, empty space bottom left for text, no text"}]}
```
Shot ids must be unique; `line` is informational.

## clip_prompts.json (not used yet — Flow clips are unreliable; skip this file for now)
```json
{"clips_out":"jobs/<slug>/flow_clips","flow_project":"Firmenfriedhof_<Slug>","max_credits":20,
 "clips":[{"id":"c001","shot":"s010","image":"jobs/<slug>/flow_img/s010.png","duration":5,"prompt":"camera move + action"}]}
```
Commit clip_prompts.json only after flow_img/DONE exists (the start images must exist).
