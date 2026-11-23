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
  const shots = spec.shots;
  const style = spec.style ? ` ${spec.style.replace(/\.?$/, ".")}` : "";
  const name = spec.flow_project ?? spec.flow_out.replace(/[^\w]+/g, "_");
  const results = {};
  const report = [];
  // Flow's agent takes up to 50 scenes per batch.
  for (let start = 0; start < shots.length; start += 40) {
    const part = shots.slice(start, start + 40);
    log(`Job ${file}: shots ${start + 1}-${start + part.length}`);
    const queued = await c.agent({
      project: name,
      scenes: part.map((s) => `${s.prompt.replace(/\.?$/, ".")}${style}`),
      aspect_ratio: spec.aspect_ratio ?? "16:9",
      download_quality: "upscaled",
    });
    const ids = queued.jobs.map((j) => j.id);
    let done;
    for (let i = 0; i < 120; i++) {
      done = await c.wait({ job_ids: ids, timeout_seconds: 300 });
      if (done.finished) break;
    }
    let files = done.jobs.flatMap((j) => j.files ?? []).filter((f) => /\.(png|jpe?g|webp)$/i.test(f)).sort();
    if (files.length < part.length) {
      // Flow often keeps drawing after the helper stops watching. Give it time, then fetch the newest images.
      log(`Only ${files.length}/${part.length} images came back; waiting for Flow, then downloading the newest ones.`);
      await sleep(4 * 60 * 1000);
      try {
        const imgs = (await c.assets({ kind: "image" })).slice(0, part.length).reverse();
        report.push({ fallback_titles: imgs.map((a) => a.name) });
        const got = await c.download({ project: `${name}_fallback_${Date.now()}`, assets: imgs.map((a) => a.name), quality: "upscaled" });
        const fb = (got.files ?? []).filter((f) => /\.(png|jpe?g|webp)$/i.test(f));
        if (fb.length > files.length) files = fb;
      } catch (e) { log("Fallback download failed:", e.message); report.push({ fallback_error: e.message }); }
    }
    done.jobs.forEach((j) => j.error && log("Flow error:", j.error));
    report.push(...done.jobs.map((j) => ({ status: j.status, error: j.error, note: j.note, progress: j.progress, failed_scenes: j.failed_scenes, files: j.files, project: j.project })));
    try { const st = await c.status({ detailed: false }); report.push({ flow_state: st.flow }); } catch (e) { report.push({ status_error: e.message }); }
    part.forEach((s, k) => {
      const f = files[k];
      if (!f) { results[s.id] = "missing"; return; }
      copyFileSync(f, join(out, `${s.id}${extname(f).toLowerCase()}`));
      results[s.id] = "flow";
    });
  }
  const missing = Object.entries(results).filter(([, v]) => v !== "flow").map(([k]) => k);
  writeFileSync(join(out, "log.json"), JSON.stringify({ made: new Date().toISOString(), results, flow_jobs: report }, null, 1));
  writeFileSync(join(out, "helper_log.txt"), tailLog());
  if (!missing.length) writeFileSync(join(out, "DONE"), new Date().toISOString());
  git("add", spec.flow_out);
  try { git("commit", "-m", `Flow images: ${spec.flow_out}${missing.length ? ` (missing ${missing.join(",")})` : ""}`); } catch {}
  git("pull", "--rebase");
  git("push");
  log(`Pushed ${Object.keys(results).length - missing.length} images to ${spec.flow_out}` + (missing.length ? `, missing ${missing}` : ""));
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

const failures = new Map();
log("Helper started.");
for (;;) {
  try {
    git("pull", "--rebase");
    if (restartIfUpdated()) { await sleep(5000); continue; }
    for (const job of findJobs()) {
      if ((failures.get(job.file) ?? 0) >= 3) continue;
      try { await runJob(job); failures.delete(job.file); }
      catch (e) { failures.set(job.file, (failures.get(job.file) ?? 0) + 1); log("Job failed:", job.file, e.message); }
    }
  } catch (e) { log("Cycle error:", e.message); }
  await sleep(EVERY_MS);
}
