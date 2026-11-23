"""Publishing queue -> GitHub release asset -> RSS feed that Zapier uploads to YouTube.

publish/queue.json: [{"id", "at" (ISO UTC), "title", "description", "tags": [...],
                      "file": repo-relative mp4 (uploaded here) OR "asset_url": already uploaded,
                      "release": tag name (default id)}]
Items whose time has come are added to publish/feed.xml (newest first). Zapier's
"RSS by Zapier -> New Item in Feed" watches the raw feed and uploads the item's link to YouTube.
"""
import datetime as dt, json, os, subprocess
from email.utils import format_datetime
from xml.sax.saxutils import escape

REPO = os.environ.get("GITHUB_REPOSITORY", "myanime317-eng/youtube-factory")
Q, FEED, DONE = "publish/queue.json", "publish/feed.xml", "publish/published.json"
now = dt.datetime.now(dt.timezone.utc)
queue = json.load(open(Q)) if os.path.exists(Q) else []
done = json.load(open(DONE)) if os.path.exists(DONE) else []
done_ids = {d["id"] for d in done}


def sh(*a):
    return subprocess.run(a, check=True, capture_output=True, text=True).stdout.strip()


for item in queue:
    if item["id"] in done_ids or item.get("hold"):  # held items wait for the owner's ok
        continue
    at = dt.datetime.fromisoformat(item["at"].replace("Z", "+00:00"))
    if at > now:
        continue
    url = item.get("asset_url")
    if not url:
        tag = item.get("release", item["id"])
        name = os.path.basename(item["file"])
        try:
            sh("gh", "release", "view", tag, "-R", REPO)
        except subprocess.CalledProcessError:
            sh("gh", "release", "create", tag, "-R", REPO, "--title", item["title"][:100], "--notes", "Firmenfriedhof upload")
        try:
            sh("gh", "release", "upload", tag, item["file"], "-R", REPO, "--clobber")
        except subprocess.CalledProcessError as e:
            print("upload failed", item["id"], e.stderr)
            continue
        url = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
        if item.get("thumb"):  # thumbnail (JPG under 2 MB) goes in the same release
            try:
                sh("gh", "release", "upload", tag, item["thumb"], "-R", REPO, "--clobber")
                item["thumb_url"] = f"https://github.com/{REPO}/releases/download/{tag}/{os.path.basename(item['thumb'])}"
            except subprocess.CalledProcessError as e:
                print("thumbnail upload failed", e.stderr)
    done.append({"id": item["id"], "title": item["title"], "description": item["description"],
                 "tags": item.get("tags", []), "url": url, "thumb_url": item.get("thumb_url", ""), "published": now.isoformat()})
    print("queued for YouTube:", item["id"], item["title"])

json.dump(done, open(DONE, "w"), ensure_ascii=False, indent=1)

items = []
for d in sorted(done, key=lambda d: d["published"], reverse=True)[:30]:
    pub = format_datetime(dt.datetime.fromisoformat(d["published"]))
    cats = "".join(f"<category>{escape(t)}</category>" for t in d["tags"])
    items.append(
        f"<item><title>{escape(d['title'])}</title><link>{escape(d['url'])}</link>"
        f"<guid isPermaLink=\"false\">{escape(d['id'])}</guid><pubDate>{pub}</pubDate>"
        f"<description><![CDATA[{d['description']}]]></description>{cats}"
        + (f"<enclosure url=\"{escape(d['thumb_url'])}\" type=\"image/jpeg\" length=\"0\"/>" if d.get("thumb_url") else "")
        + "</item>")
feed = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel>"
        "<title>Firmenfriedhof uploads</title><link>https://www.youtube.com/@derfirmenfriedhof</link>"
        "<description>Upload queue</description>" + "".join(items) + "</channel></rss>")
os.makedirs("publish", exist_ok=True)
open(FEED, "w").write(feed)
