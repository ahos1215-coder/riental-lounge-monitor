#!/usr/bin/env node
/**
 * ローカル Next のブログ系 API を軽く叩く（LINE / Cron）。
 *
 * 前提: `cd frontend && npm run dev` で http://localhost:3000 が起動していること。
 *
 *   npm run smoke:blog-apis              # ヘルス + Cron 401 + 可能なら Cron 本番（要 CRON_SECRET または SKIP_CRON_AUTH）
 *   npm run smoke:blog-apis -- --quick   # ヘルス + Cron 401 のみ
 *   npm run smoke:blog-apis -- --url=http://127.0.0.1:3000
 *
 * .env.local（リポジトリルート or frontend）に CRON_SECRET / SKIP_CRON_AUTH を置くと load します。
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readText(fp) {
  return fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
}

function parseEnvFile(fp) {
  if (!fs.existsSync(fp)) return;
  for (const line of readText(fp).split(/\r?\n/)) {
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
  let quick = false;
  let baseUrl = process.env.SMOKE_BASE_URL || "http://127.0.0.1:3000";
  for (const a of argv) {
    if (a === "--quick") quick = true;
    else if (a.startsWith("--url=")) baseUrl = a.slice(6).replace(/\/+$/, "");
  }
  return { quick, baseUrl };
}

async function fetchJson(url, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? 120_000;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    const text = await res.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
    return { ok: res.ok, status: res.status, body };
  } finally {
    clearTimeout(t);
  }
}

/** Windows で fetch 直後の process.exit が libuv アサーションを起こすのを避ける */
async function exitWithCode(code) {
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setTimeout(r, 50));
  process.exit(code);
}

const frontendRoot = resolveFrontendRoot(__dirname);
loadEnv(frontendRoot);
const { quick, baseUrl } = parseArgs(process.argv.slice(2));

console.log("[smoke] baseUrl:", baseUrl);
console.log("[smoke] env hints:", {
  hasGEMINI: Boolean(process.env.GEMINI_API_KEY?.trim()),
  hasSupabase: Boolean(
    (process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY) ||
      (process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_KEY)
  ),
  hasCRON_SECRET: Boolean(process.env.CRON_SECRET?.trim()),
  skipCronAuth: process.env.SKIP_CRON_AUTH === "1",
});

let failed = false;
function fail(msg) {
  console.error("[smoke] FAIL:", msg);
  failed = true;
}

// 1) LINE ヘルス
{
  const r = await fetchJson(`${baseUrl}/api/line`, { timeoutMs: 15_000 });
  if (r.status !== 200) fail(`/api/line expected 200, got ${r.status}`);
  else if (typeof r.body === "object" && r.body?.service === "line-webhook") {
    console.log("[smoke] OK  GET /api/line", r.body);
  } else {
    console.log("[smoke] OK  GET /api/line", r.body);
  }
}

// 2) Cron 未認証 → 401（SKIP_CRON_AUTH=1 のときは未認証 GET がフル処理を走らせるためテスト省略）
if (process.env.SKIP_CRON_AUTH === "1") {
  console.log("[smoke] SKIP  Cron 401 テスト（SKIP_CRON_AUTH=1 では未認証でも処理が走るため）");
} else {
  const r = await fetchJson(`${baseUrl}/api/cron/blog-draft`, { timeoutMs: 15_000 });
  if (r.status !== 401) {
    fail(`/api/cron/blog-draft without auth: expected 401, got ${r.status}`);
  } else {
    console.log("[smoke] OK  GET /api/cron/blog-draft → 401 (unauthorized)");
  }
}

if (quick) {
  console.log(failed ? "\n[smoke] 完了（一部失敗）" : "\n[smoke] 完了（--quick）");
  await exitWithCode(failed ? 1 : 0);
}

// 3) Cron 認証あり（フルパイプライン: Backend + Gemini + Supabase に依存）
const secret = process.env.CRON_SECRET?.trim();
const headers = {};
if (secret) headers.Authorization = `Bearer ${secret}`;

if (!secret && process.env.SKIP_CRON_AUTH !== "1") {
  console.log(
    "[smoke] SKIP: フル Cron を試さず終了（CRON_SECRET を .env.local に入れるか、SKIP_CRON_AUTH=1 で dev サーバを起動して再実行）"
  );
  await exitWithCode(failed ? 1 : 0);
}

console.log("[smoke] 実行 GET /api/cron/blog-draft（認証付き・最大2分）…");
const full = await fetchJson(`${baseUrl}/api/cron/blog-draft`, {
  timeoutMs: 120_000,
  headers,
});
console.log("[smoke] Cron 応答 status=", full.status, "body=", JSON.stringify(full.body, null, 2));

if (full.status !== 200) fail(`Cron authenticated call expected 200, got ${full.status}`);
else if (typeof full.body === "object" && full.body?.ok === false) {
  console.warn("[smoke] WARN: JSON ok=false（Backend 未起動・GEMINI 未設定・店舗データ等を確認）");
}

await exitWithCode(failed ? 1 : 0);
