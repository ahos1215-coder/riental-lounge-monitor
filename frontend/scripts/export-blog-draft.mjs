#!/usr/bin/env node
/**
 * Supabase blog_drafts → ローカル MDX + 公開 Facts JSON
 *
 * 前提: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY（または SUPABASE_SERVICE_KEY）
 * ルートの .env.local から読み込み（generate-public-facts.mjs と同様）
 *
 * 使い方:
 *   cd frontend
 *   npm run drafts:export -- --list
 *   npm run drafts:export -- --latest
 *   npm run drafts:export -- --id=<uuid>
 *   npm run drafts:export -- --latest --force --update-index
 *
 * --dry-run : 書き込まずパスのみ表示
 * --force   : 既存ファイルを上書き
 * --update-index : content/facts/public/index.json にエントリを追加（重複時はスキップ）
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import matter from "gray-matter";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = val;
  }
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

function loadEnv(frontendRoot) {
  const repoRoot = path.dirname(frontendRoot);
  parseEnvFile(path.join(repoRoot, ".env.local"));
  parseEnvFile(path.join(frontendRoot, ".env.local"));
}

function parseArgs(argv) {
  const out = {
    list: false,
    latest: false,
    id: "",
    dryRun: false,
    force: false,
    updateIndex: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--list") out.list = true;
    else if (a === "--latest") out.latest = true;
    else if (a === "--dry-run") out.dryRun = true;
    else if (a === "--force") out.force = true;
    else if (a === "--update-index") out.updateIndex = true;
    else if (a.startsWith("--id=")) out.id = a.slice(5);
    else if (a === "--id" && argv[i + 1]) out.id = String(argv[++i]);
  }
  return out;
}

function getSupabaseConfig() {
  const url = (process.env.SUPABASE_URL || "").replace(/\/$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY || "";
  if (!url || !key) {
    console.error(
      "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SERVICE_KEY). Set in .env.local at repo root."
    );
    process.exit(1);
  }
  return { url, key };
}

async function restSelect(config, queryPath) {
  const res = await fetch(`${config.url}/rest/v1/${queryPath}`, {
    headers: {
      apikey: config.key,
      Authorization: `Bearer ${config.key}`,
      Accept: "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Supabase REST ${res.status}: ${body.slice(0, 500)}`);
  }
  return res.json();
}

function normalizePublicFacts(row) {
  let raw = row.insight_json;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = {};
    }
  }
  if (!raw || typeof raw !== "object") raw = {};
  return {
    facts_id: raw.facts_id ?? row.facts_id,
    store: raw.store ?? row.store_slug,
    range: raw.range ?? {},
    insight: raw.insight ?? {},
    quality_flags: raw.quality_flags ?? { notes: [] },
    source: raw.source ?? "api/range",
    shift: raw.shift ?? "none",
    draft_context: raw.draft_context ?? {},
  };
}

function safeWrite(fp, content, { dryRun, force }) {
  if (dryRun) {
    console.log(`[dry-run] would write: ${fp}`);
    return;
  }
  if (fs.existsSync(fp) && !force) {
    console.error(`Refusing to overwrite (use --force): ${fp}`);
    process.exit(1);
  }
  fs.mkdirSync(path.dirname(fp), { recursive: true });
  fs.writeFileSync(fp, content, "utf8");
  console.log(`Wrote: ${fp}`);
}

function maybeUpdateIndex(frontendRoot, row, mdxContent, { dryRun, force }) {
  const indexPath = path.join(frontendRoot, "content", "facts", "public", "index.json");
  if (!fs.existsSync(indexPath)) {
    console.warn("No index.json found; skip --update-index");
    return;
  }
  const slug = row.facts_id;
  const data = JSON.parse(readText(indexPath));
  if (!Array.isArray(data.facts)) data.facts = [];
  if (data.facts.some((e) => e.slug === slug)) {
    console.log(`index.json already has slug=${slug}, skip`);
    return;
  }
  let level = "normal";
  try {
    const fm = matter(mdxContent);
    if (fm.data?.level) level = String(fm.data.level);
  } catch {
    /* ignore */
  }
  const dateStr = String(row.target_date).slice(0, 10);
  const entry = {
    slug,
    store: { id: row.store_slug },
    date: dateStr,
    level,
  };
  data.facts.push(entry);
  if (!data.latest_by_store) data.latest_by_store = {};
  data.latest_by_store[row.store_slug] = slug;

  if (dryRun) {
    console.log(`[dry-run] would append to index.json:`, entry);
    return;
  }
  fs.writeFileSync(indexPath, JSON.stringify(data, null, 2) + "\n", "utf8");
  console.log(`Updated: ${indexPath}`);
}

async function exportOne(row, frontendRoot, opts) {
  const slug = row.facts_id;
  if (!slug) {
    console.error("Row missing facts_id");
    process.exit(1);
  }
  const blogPath = path.join(frontendRoot, "content", "blog", `${slug}.mdx`);
  const factsPath = path.join(frontendRoot, "content", "facts", "public", `${slug}.json`);
  const factsBody = JSON.stringify(normalizePublicFacts(row), null, 2) + "\n";

  safeWrite(blogPath, row.mdx_content || "", opts);
  safeWrite(factsPath, factsBody, opts);

  if (opts.updateIndex) {
    maybeUpdateIndex(frontendRoot, row, row.mdx_content || "", opts);
  }
}

async function main() {
  const frontendRoot = resolveFrontendRoot(process.cwd());
  loadEnv(frontendRoot);
  const args = parseArgs(process.argv.slice(2));
  const config = getSupabaseConfig();

  if (args.list) {
    const rows = await restSelect(config, "blog_drafts?select=id,created_at,facts_id,store_slug,target_date,source&order=created_at.desc&limit=20");
    console.log(JSON.stringify(rows, null, 2));
    return;
  }

  let row;
  if (args.id) {
    const rows = await restSelect(config, `blog_drafts?select=*&id=eq.${encodeURIComponent(args.id)}`);
    row = rows[0];
    if (!row) {
      console.error("No row for id=", args.id);
      process.exit(1);
    }
  } else if (args.latest) {
    const rows = await restSelect(config, "blog_drafts?select=*&order=created_at.desc&limit=1");
    row = rows[0];
    if (!row) {
      console.error("blog_drafts is empty");
      process.exit(1);
    }
  } else {
    console.log(`Usage:
  npm run drafts:export -- --list
  npm run drafts:export -- --latest [--force] [--dry-run] [--update-index]
  npm run drafts:export -- --id=<uuid> [--force] [--dry-run] [--update-index]
`);
    process.exit(1);
  }

  console.log("Exporting draft:", row.id, row.facts_id, row.created_at);
  await exportOne(row, frontendRoot, args);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
