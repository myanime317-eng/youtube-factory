// Firmenfriedhof laptop helper.
// Runs quietly whenever the laptop is on. Every few minutes it pulls the youtube-factory repo, looks for
// image jobs (any image_prompts.json with a "flow_out" folder that has no DONE file), makes the images in
// Google Flow (Nano Banana, 0 credits) through flow-mcp, copies them into the repo and pushes them back.
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { appendFileSync, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { extname, join } from "node:path";
import { pathToFileURL } from "node:url";

const HOME = homedir();
const REPO = process.env.FF_REPO ?? join(HOME, "youtube-factory");
const FLOW = process.env.FF_FLOW ?? join(HOME, "flow-mcp");
const STATE = join(HOME, ".flow-mcp");
const LOG = join(STATE, "firmenfriedhof-helper.log");
const PROJECT_FILE = join(STATE, "firmenfriedhof-project.txt");
const EVERY_MS = 5 * 60 * 1000;
mkdirSync(STATE, { recursive: true });

const log = (...a) => {
  const line = `[${new Date().toISOString()}] ${a.join(" ")}\n`;
  process.stdout.write(line);
  try { appendFileSync(LOG, line); } catch {}
};
const git = (...args) => {
  const r = spawnSync("git", args, { cwd: REPO, encoding: "utf8", windowsHide: true });
  if (r.status !== 0) throw new Error(`git ${args.join(" ")}: ${(r.stderr || r.stdout || "").trim()}`);
  return r.stdout.trim();
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// One helper at a time: hold a local port as a lock (a restarting helper gets a few tries).
for (let tryNo = 0; ; tryNo++) {
  const ok = await new Promise((done) => {
    const s = (globalThis.__lock = createServer());
    s.once("error", () => done(false));
    s.listen(8799, "127.0.0.1", () => done(true));
  });
  if (ok) break;
  if (tryNo >= 5) { log("Another helper is already running. Exiting."); process.exit(0); }
  await sleep(3000);
}

const imp = (f) => import(pathToFileURL(join(FLOW, "dist", f)).href);
const { LocalCore } = await imp("core.js");
const { startServer } = await imp("server.js");
const { RemoteCore } = await imp("remote.js");
const { getFlowPage } = await imp("chrome.js");

let core = null;
async function getCore() {
  if (core) return core;
  const local = new LocalCore();
  const role = await startServer(local);
  if (role === "none") throw new Error("Port 8787 is used by another program.");
  // Owner: this process runs the Flow queue (Studio still works at 127.0.0.1:8787).
  // Client: Studio or Claude already owns Flow, so send the work to it.
  core = role === "owner" ? local : new RemoteCore();
  log(role === "owner" ? "Running Flow myself." : "Using the Flow Studio that is already open.");
  return core;
}

async function ensureProject(c) {
  const page = await getFlowPage();
  if (/\/project\//.test(page.url())) return;
  const saved = existsSync(PROJECT_FILE) ? readFileSync(PROJECT_FILE, "utf8").trim() : "";
  if (saved) {
    await page.goto(saved, { waitUntil: "domcontentloaded" });
    await sleep(6000);
    if (/\/project\//.test(page.url())) return;
  }
  const made = await c.new_project({ title: "Firmenfriedhof" });
  writeFileSync(PROJECT_FILE, made.url ?? page.url());
  log("Created Flow project", made.url ?? "");
}

function findJobs() {
  const jobs = [];
  const walk = (dir, depth) => {
    if (depth > 4 || !existsSync(dir)) return;
    for (const name of readdirSync(dir)) {
      if (name.startsWith(".") || name === "node_modules") continue;
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p, depth + 1);
      else if (name === "clip_prompts.json") {
        try {
          const spec = JSON.parse(readFileSync(p, "utf8"));
          if (spec.clips_out && !existsSync(join(REPO, spec.clips_out, "DONE"))) jobs.push({ file: p, spec, kind: "clips" });
        } catch (e) { log("Bad clip job file", p, e.message); }
      }
      else if (name === "image_prompts.json") {
        try {
          const spec = JSON.parse(readFileSync(p, "utf8"));
          if (spec.flow_out && !existsSync(join(REPO, spec.flow_out, "DONE"))) jobs.push({ file: p, spec });
        } catch (e) { log("Bad job file", p, e.message); }
      }
    }
  };
  walk(join(REPO, "test"), 0);
  walk(join(REPO, "jobs"), 0);
  return jobs;
}

async function runJob({ file, spec }) {
  const c = await getCore();
  await ensureProject(c);
  const out = join(REPO, spec.flow_out);
  mkdirSync(out, { recursive: true });
  // manifest = images this code placed and matched to their scene; anything else in the folder is not trusted
  const mpath = join(out, "manifest.json");
  const manifest = existsSync(mpath) ? JSON.parse(readFileSync(mpath, "utf8")) : {};
  const ok = (id) => manifest[id] && existsSync(join(out, manifest[id]));
  const shots = spec.shots.filter((s) => !ok(s.id));
  const style = spec.style ? ` ${spec.style.replace(/\.?$/, ".")}` : "";
  const name = spec.flow_project ?? spec.flow_out.replace(/[^\w]+/g, "_");
  const report = [];
  const BATCH = 20;
  for (let start = 0; start < shots.length; start += BATCH) {
    const part = shots.slice(start, start + BATCH);
    log(`Job ${file}: ${part.length} images (${shots.length - start} left)`);
    // own folder per batch, so file numbers scene-01.. match this batch's scene order exactly
    const queued = await c.agent({
      project: `${name}_${Date.now()}`,
      scenes: part.map((s) => `${s.prompt.replace(/\.?$/, ".")}${style}`),
      aspect_ratio: spec.aspect_ratio ?? "16:9",
      download_quality: "upscaled",
    });
    const ids = queued.jobs.map((j) => j.id);
    let done;
    for (let i = 0; i < 60; i++) {
      done = await c.wait({ job_ids: ids, timeout_seconds: 300 });
      if (done.finished) break;
    }
    done.jobs.forEach((j) => j.error && log("Flow error:", j.error));
    report.push(...done.jobs.map((j) => ({ status: j.status, error: j.error, note: j.note, failed_scenes: j.failed_scenes, files: j.files })));
    let files = done.jobs.flatMap((j) => j.files ?? []).filter((f) => /\.(png|jpe?g|webp)$/i.test(f));
    if (!files.length) {
      // Agent mode failed (Flow UI changes): make this batch one image at a time instead (stills cost no credits)
      log("Agent batch gave nothing; making these images one by one.");
      const q2 = await c.generate({
        project: `${name}_single_${Date.now()}`,
        scenes: part.map((s) => ({ prompt: `${s.prompt.replace(/\.?$/, ".")}${style}`, type: "image",
          aspect_ratio: spec.aspect_ratio ?? "16:9", max_credits: 0, download_quality: "upscaled" })),
      });
      const ids2 = q2.jobs.map((j) => j.id);
      let d2;
      for (let i = 0; i < 120; i++) {
        d2 = await c.wait({ job_ids: ids2, timeout_seconds: 300 });
        if (d2.finished) break;
      }
      d2.jobs.forEach((j) => j.error && log("Flow error (single):", String(j.error).slice(0, 200)));
      report.push(...d2.jobs.map((j) => ({ single: true, status: j.status, error: j.error, files: j.files })));
      files = d2.jobs.flatMap((j) => j.files ?? []).filter((f) => /\.(png|jpe?g|webp)$/i.test(f));
    }
    let got = 0;
    for (const f of files) {
      const m = /scene-(\d+)/.exec(f.split(/[\\/]/).pop());
      const s = m && part[Number(m[1]) - 1];
      if (!s) continue;
      const fname = `${s.id}${extname(f).toLowerCase()}`;
      copyFileSync(f, join(out, fname));
      manifest[s.id] = fname;
      got++;
    }
    writeFileSync(mpath, JSON.stringify(manifest, null, 1));
    log(`Batch: ${got}/${part.length} images matched`);
    try {  // save progress after each batch
      git("add", spec.flow_out);
      git("commit", "-m", `Flow images: ${spec.flow_out} (${Object.keys(manifest).length}/${spec.shots.length})`);
      git("pull", "--rebase");
      git("push");
    } catch (e) { log("progress push skipped:", e.message.slice(0, 120)); }
  }
  const missing = spec.shots.filter((s) => !ok(s.id)).map((s) => s.id);
  writeFileSync(join(out, "log.json"), JSON.stringify({ made: new Date().toISOString(), missing, flow_jobs: report }, null, 1));
  writeFileSync(join(out, "helper_log.txt"), tailLog());
  if (!missing.length) writeFileSync(join(out, "DONE"), new Date().toISOString());
  git("add", spec.flow_out);
  try { git("commit", "-m", `Flow images: ${spec.flow_out}${missing.length ? ` (${missing.length} still missing, retrying next round)` : " DONE"}`); } catch {}
  git("pull", "--rebase");
  git("push");
  log(`Images: ${spec.shots.length - missing.length}/${spec.shots.length}` + (missing.length ? `, missing ${missing.join(",")}` : ""));
}

function tailLog() {
  try { return readFileSync(LOG, "utf8").split("\n").slice(-150).join("\n"); } catch { return ""; }
}

// Restart with the new code when the helper itself was updated on GitHub.
const SELF = join(REPO, "laptop", "helper.mjs");
const selfStamp = () => { try { return readFileSync(SELF, "utf8").length + ":" + statSync(SELF).mtimeMs; } catch { return ""; } };
let myStamp = selfStamp();
function restartIfUpdated() {
  if (selfStamp() === myStamp) return;
  log("Helper code updated, restarting.");
  try { globalThis.__lock.close(); } catch {}
  const child = spawn(process.execPath, [SELF], { cwd: REPO, detached: true, stdio: "ignore", windowsHide: true });
  child.unref();
  setTimeout(() => process.exit(0), 500);
  return true;
}


async function runClips({ file, spec }) {
  const c = await getCore();
  await ensureProject(c);
  const out = join(REPO, spec.clips_out);
  mkdirSync(out, { recursive: true });
  const results = {};
  const report = [];
  const todo = spec.clips.filter((k) => !existsSync(join(out, `${k.id}.mp4`)));
  if (!todo.length) { writeFileSync(join(out, "DONE"), new Date().toISOString()); }
  for (const k of todo) {
    const first = k.image ? join(REPO, k.image) : undefined;
    if (first && !existsSync(first)) { results[k.id] = "no start image yet"; continue; }
    log(`Clip ${k.id}: ${k.prompt.slice(0, 60)}`);
    const q = await c.generate({
      project: spec.flow_project ?? spec.clips_out.replace(/[^\w]+/g, "_"),
      scenes: [{
        prompt: k.prompt, type: "video", aspect_ratio: "16:9", duration: k.duration ?? 5,
        resolution: "720p", max_credits: spec.max_credits ?? 20, download_quality: "upscaled",
        ...(first ? { first_frame: first } : {}),
      }],
    });
    const ids = q.jobs.map((j) => j.id);
    let done;
    for (let i = 0; i < 60; i++) { done = await c.wait({ job_ids: ids, timeout_seconds: 300 }); if (done.finished) break; }
    const j = done.jobs[0];
    report.push({ id: k.id, status: j.status, error: j.error, note: j.note, credits: j.credits, files: j.files });
    const f = (j.files ?? []).find((x) => /\.mp4$/i.test(x));
    if (f) { copyFileSync(f, join(out, `${k.id}.mp4`)); results[k.id] = "flow"; }
    else results[k.id] = j.error || j.note || j.status;
    if (/credit/i.test(String(j.error ?? j.note ?? ""))) { log("Out of Flow credits for today; the rest waits for tomorrow."); break; }
  }
  const missing = spec.clips.filter((k) => !existsSync(join(out, `${k.id}.mp4`))).map((k) => k.id);
  writeFileSync(join(out, "log.json"), JSON.stringify({ made: new Date().toISOString(), results, flow_jobs: report }, null, 1));
  writeFileSync(join(out, "helper_log.txt"), tailLog());
  if (!missing.length) writeFileSync(join(out, "DONE"), new Date().toISOString());
  git("add", spec.clips_out);
  try { git("commit", "-m", `Flow clips: ${spec.clips_out}${missing.length ? ` (waiting: ${missing.join(",")})` : ""}`); } catch {}
  git("pull", "--rebase");
  git("push");
  log(`Clips pushed; waiting: ${missing.join(",") || "none"}`);
  // Don't hammer Flow when a day's credits are used up: try again in 6 hours.
  if (missing.length) clipPauseUntil = Date.now() + 6 * 3600 * 1000;
}
let clipPauseUntil = 0;

const failures = new Map();
log("Helper started.");
for (;;) {
  try {
    git("pull", "--rebase");
    if (restartIfUpdated()) { await sleep(5000); continue; }
    for (const job of findJobs()) {
      if ((failures.get(job.file) ?? 0) >= 3) continue;
      if (job.kind === "clips" && Date.now() < clipPauseUntil) continue;
      try { await (job.kind === "clips" ? runClips(job) : runJob(job)); failures.delete(job.file); }
      catch (e) { failures.set(job.file, (failures.get(job.file) ?? 0) + 1); log("Job failed:", job.file, e.message); }
    }
  } catch (e) { log("Cycle error:", e.message); }
  await sleep(EVERY_MS);
}
