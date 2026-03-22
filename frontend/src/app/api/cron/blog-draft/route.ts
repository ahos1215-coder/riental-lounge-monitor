import path from "node:path";
import { loadEnvConfig } from "@next/env";
import { NextRequest, NextResponse } from "next/server";

import { DEFAULT_STORE, getStoreMetaBySlugStrict } from "@/app/config/stores";
import { buildFactsId } from "@/lib/line/parseLineIntent";
import { runBlogDraftPipeline } from "@/lib/blog/runBlogDraftPipeline";

// Turbopack の API ルートでは `next.config.ts` の loadEnvConfig が効かないケースがあるため、
// リポジトリルート / frontend の `.env.local` をここでも読み込む（CRON_SECRET の照合用）。
loadEnvConfig(path.resolve(process.cwd(), ".."));
loadEnvConfig(process.cwd());

const BACKEND_URL =
  process.env.BACKEND_URL ??
  process.env["BACKEND-URL"] ??
  "http://127.0.0.1:5000";

function cronRangeLimit(): number {
  const raw = process.env.BLOG_CRON_RANGE_LIMIT?.trim();
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  if (Number.isFinite(n) && n > 0) return Math.min(n, 50_000);
  return 500;
}

function todayYmdJst(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function parseCronStoreSlugs(): string[] {
  const raw =
    process.env.BLOG_CRON_STORE_SLUGS?.trim() ||
    process.env.BLOG_CRON_STORE_SLUG?.trim() ||
    DEFAULT_STORE;
  return raw
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * Vercel Cron: `Authorization: Bearer <CRON_SECRET>`（プロジェクトに CRON_SECRET があるとき自動付与）
 * ローカル: `.env.local` に CRON_SECRET を入れて同じヘッダで叩くか、`SKIP_CRON_AUTH=1`（development のみ）
 */
function isCronAuthorized(req: NextRequest): boolean {
  if (process.env.NODE_ENV === "development" && process.env.SKIP_CRON_AUTH === "1") {
    return true;
  }
  const secret = process.env.CRON_SECRET?.trim();
  if (!secret) return false;
  const auth = req.headers.get("authorization");
  return auth === `Bearer ${secret}`;
}

export const maxDuration = 60;

export async function GET(req: NextRequest) {
  return handleCron(req);
}

export async function POST(req: NextRequest) {
  return handleCron(req);
}

async function handleCron(req: NextRequest) {
  if (!isCronAuthorized(req)) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(req.url);
  const dateOverride = url.searchParams.get("date");
  const dateYmd = dateOverride && /^\d{4}-\d{2}-\d{2}$/.test(dateOverride) ? dateOverride : todayYmdJst();

  const slugs = parseCronStoreSlugs();
  const rangeLimit = cronRangeLimit();

  const results: Array<{
    slug: string;
    ok: boolean;
    facts_id?: string;
    edition?: string;
    db?: { saved: boolean; id?: string; error?: string; skippedReason?: string };
    error?: string;
  }> = [];

  for (const slug of slugs) {
    const store = getStoreMetaBySlugStrict(slug);
    if (!store) {
      results.push({ slug, ok: false, error: `unknown store slug: ${slug}` });
      continue;
    }

    const factsId = buildFactsId(store.slug, dateYmd);
    const out = await runBlogDraftPipeline({
      backendUrl: BACKEND_URL,
      rangeLimit,
      store,
      dateYmd,
      factsId,
      topicHint: "",
      source: "vercel_cron",
      lineUserId: null,
    });

    if (!out.ok) {
      results.push({ slug, ok: false, facts_id: out.factsId, error: out.error });
      continue;
    }

    results.push({
      slug,
      ok: true,
      facts_id: out.factsId,
      edition: out.insightResult.draft_context.edition,
      db: out.db,
    });
  }

  const allOk = results.every((r) => r.ok);
  /** Cron は 200 のみにし、失敗は JSON の `ok` で判別（Vercel の再試行を避ける） */
  return NextResponse.json({
    ok: allOk,
    service: "cron-blog-draft",
    dateYmd,
    rangeLimit,
    edition_inferred: results.find((r) => r.edition)?.edition,
    results,
  });
}
