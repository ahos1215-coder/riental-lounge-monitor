import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
// 夜窓インサイトの純粋関数は scripts/lib/insightCore.mjs（src/lib/blog/insightFromRange.ts の鏡像）。
import {
  collectPoints,
  computeInsight,
  nightWindowIso,
  pickArray,
} from "./lib/insightCore.mjs";

function readText(fp) {
  return fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
}

function parseEnvFile(fp) {
  if (!fs.existsSync(fp)) return;
  const lines = readText(fp).split(/\r?\n/);
  for (const line of lines) {
    const s = line.trim();
    if (!s || s.startsWith("#")) continue;
    const idx = s.indexOf("=");
    if (idx < 0) continue;
    const key = s.slice(0, idx).trim();
    let val = s.slice(idx + 1).trim();
    if ((val.startsWith("\"") && val.endsWith("\"")) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = val;
  }
}

function parseArgs(argv) {
  const out = { slug: "", backend: "", limit: "" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--slug" && argv[i + 1]) out.slug = String(argv[++i]);
    else if (a.startsWith("--slug=")) out.slug = a.split("=", 2)[1] ?? "";
    else if (a === "--backend" && argv[i + 1]) out.backend = String(argv[++i]);
    else if (a.startsWith("--backend=")) out.backend = a.split("=", 2)[1] ?? "";
    else if (a === "--limit" && argv[i + 1]) out.limit = String(argv[++i]);
    else if (a.startsWith("--limit=")) out.limit = a.split("=", 2)[1] ?? "";
  }
  return out;
}

function hasBlogDir(dir) {
  return fs.existsSync(path.join(dir, "content", "blog"));
}

function resolveFrontendRoot(startDir) {
  if (hasBlogDir(startDir)) return startDir;
  const directFrontend = path.join(startDir, "frontend");
  if (hasBlogDir(directFrontend)) return directFrontend;

  let current = startDir;
  for (let i = 0; i < 3; i++) {
    const parent = path.dirname(current);
    if (parent === current) break;
    if (hasBlogDir(parent)) return parent;
    const parentFrontend = path.join(parent, "frontend");
    if (hasBlogDir(parentFrontend)) return parentFrontend;
    current = parent;
  }
  return startDir;
}

function pickString(obj, keys) {
  for (const k of keys) {
    const v = obj?.[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

function pickFactsId(data) {
  return pickString(data, ["facts_id", "factsId", "facts_id_public"]);
}

function pickStore(data) {
  return pickString(data, ["storeId", "store", "store_id"]);
}

function pickDate(data) {
  return pickString(data, ["date"]);
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`fetch failed: ${res.status} ${res.statusText} (${url})`);
  return res.json();
}

async function fetchRange(backend, store, limit) {
  const base = backend.replace(/\/$/, "");
  const url = `${base}/api/range?store=${encodeURIComponent(store)}&limit=${encodeURIComponent(String(limit))}`;
  const data = await fetchJson(url);
  return pickArray(data);
}

async function fetchForecastToday(backend, store) {
  const base = backend.replace(/\/$/, "");
  const url = `${base}/api/forecast_today?store=${encodeURIComponent(store)}`;
  const data = await fetchJson(url);
  return pickArray(data);
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function writeJson(fp, obj) {
  ensureDir(path.dirname(fp));
  fs.writeFileSync(fp, JSON.stringify(obj, null, 2) + "\n", "utf8");
}

function errorMessage(err) {
  if (typeof err === "string") return err;
  if (err && typeof err === "object" && "message" in err) return String(err.message);
  return String(err);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const frontendRoot = resolveFrontendRoot(process.cwd());
  parseEnvFile(path.join(frontendRoot, ".env.local"));

  const onlySlug = args.slug;
  const limitRaw = Number(args.limit || "1000");
  const limit = Number.isFinite(limitRaw) && limitRaw > 0 ? Math.floor(limitRaw) : 1000;
  const backend =
    args.backend ||
    process.env.BACKEND_URL ||
    "http://127.0.0.1:5000";

  const blogDir = path.join(frontendRoot, "content", "blog");
  const factsPublicDir = path.join(frontendRoot, "content", "facts", "public");

  if (!fs.existsSync(blogDir)) throw new Error(`not found: ${blogDir}`);

  const files = fs.readdirSync(blogDir).filter((f) => /\.mdx?$/i.test(f));
  const targets = [];

  for (const f of files) {
    const slug = f.replace(/\.mdx?$/i, "");
    const raw = readText(path.join(blogDir, f));
    const parsed = matter(raw);

    const factsId = pickFactsId(parsed.data);
    const store = pickStore(parsed.data);
    const date = pickDate(parsed.data);

    if (!factsId || !store || !date) continue;
    if (onlySlug && !(slug === onlySlug || factsId === onlySlug)) continue;

    targets.push({ slug, factsId, store, date });
  }

  if (targets.length === 0) {
    console.log("no targets (facts_id + store + date) found.");
    process.exit(0);
  }

  console.log(`backend: ${backend}`);
  console.log(`targets: ${targets.length}`);

  for (const t of targets) {
    const { from, to, label } = nightWindowIso(t.date);
    const notes = [];
    let source = "api/range";
    let shift = "none";
    let points = [];

    try {
      const rows = await fetchRange(backend, t.store, limit);
      points = collectPoints(rows, from, to, {
        totalKeys: ["total"],
        menKeys: ["men", "male", "m"],
        womenKeys: ["women", "female", "f"],
      });
    } catch (e) {
      notes.push(`api_range_error:${errorMessage(e)}`);
    }

    if (points.length === 0) {
      source = "api/forecast_today";
      let forecastRows = [];
      try {
        forecastRows = await fetchForecastToday(backend, t.store);
      } catch (e) {
        notes.push(`forecast_error:${errorMessage(e)}`);
      }

      if (forecastRows.length > 0) {
        points = collectPoints(forecastRows, from, to, {
          totalKeys: ["total_pred", "total"],
          menKeys: ["men_pred", "men", "male", "m"],
          womenKeys: ["women_pred", "women", "female", "f"],
        });

        if (points.length === 0) {
          const shifted = collectPoints(forecastRows, from, to, {
            totalKeys: ["total_pred", "total"],
            menKeys: ["men_pred", "men", "male", "m"],
            womenKeys: ["women_pred", "women", "female", "f"],
            shiftDays: 1,
          });
          if (shifted.length > 0) {
            points = shifted;
            shift = "+1day";
          }
        }
      }
    }

    if (points.length === 0) notes.push("no_samples_in_window");

    const insight = computeInsight(points);
    const out = {
      facts_id: t.factsId,
      store: t.store,
      range: { label, from, to },
      insight: {
        peak_time: insight.peak_time,
        avoid_time: insight.avoid_time,
        crowd_label: insight.crowd_label,
      },
      quality_flags: {
        notes: [`generated_from:${source}`, `shift:${shift}`, ...notes],
      },
    };

    const outPath = path.join(factsPublicDir, `${t.factsId}.json`);
    writeJson(outPath, out);
    console.log(`wrote: ${path.relative(frontendRoot, outPath)}`);
  }

  console.log("done");
}

await main();
