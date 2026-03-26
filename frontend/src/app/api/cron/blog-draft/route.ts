import path from "node:path";
import crypto from "node:crypto";
import { loadEnvConfig } from "@next/env";
import { NextRequest, NextResponse } from "next/server";

import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import { buildFactsId } from "@/lib/line/parseLineIntent";
import type { BlogEdition } from "@/lib/blog/insightFromRange";
import {
  runBlogDraftPipeline,
  type BlogDraftPipelineSource,
} from "@/lib/blog/runBlogDraftPipeline";
import { insertBlogDraft, isBlogDraftsConfigured } from "@/lib/supabase/blogDrafts";

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

/**
 * 1リクエスト=1店舗の下書き生成（GHA matrix）なので、Vercel の maxDuration(60s) に寄せて余裕を確保する。
 * 45s だと Gemini + バックエンド取得で間に合わない店舗が出て `mdx_content=""` が保存されてしまう。
 */
const REQUEST_BUDGET_MS = 58_000;

function parseRequestedStoreSlug(url: URL): string | null {
  const raw = url.searchParams.get("store")?.trim().toLowerCase();
  if (raw) return raw;
  const fallback = process.env.BLOG_CRON_STORE_SLUG?.trim().toLowerCase();
  return fallback || null;
}

function buildStableFactsId(
  storeSlug: string,
  dateYmd: string,
  edition: BlogEdition | undefined,
  source: BlogDraftPipelineSource,
): string {
  // SEO 用: 定時自動投稿は固定IDで上書き運用（URL固定を想定）
  if (source === "github_actions_cron" || source === "vercel_cron" || source === "github_actions_retry") {
    const slot = edition ?? "nightly";
    return `auto_${storeSlug}_${slot}`;
  }
  return buildFactsId(storeSlug, dateYmd);
}

/**
 * 定時 Cron（本番は GitHub Actions から `GET` + `?edition=`）。`Authorization: Bearer <CRON_SECRET>`。
 * ローカル: `.env.local` に CRON_SECRET を入れて同じヘッダで叩くか、`SKIP_CRON_AUTH=1`（development のみ）
 */
function isCronAuthorized(req: NextRequest): boolean {
  if (process.env.NODE_ENV === "development" && process.env.SKIP_CRON_AUTH === "1") {
    return true;
  }
  const secret = process.env.CRON_SECRET?.trim();
  if (!secret) return false;
  const auth = req.headers.get("authorization");
  if (!auth) return false;
  const expected = Buffer.from(`Bearer ${secret}`);
  const received = Buffer.from(auth);
  if (expected.length !== received.length) return false;
  return crypto.timingSafeEqual(expected, received);
}

/** Vercel Serverless の実行上限に合わせる（Hobby も max 60s まで設定可能。バックエンド大量取得＋Gemini に余裕を持たせる） */
export const maxDuration = 60;

export async function GET(req: NextRequest) {
  return handleCron(req);
}

export async function POST(req: NextRequest) {
  return handleCron(req);
}

async function handleCron(req: NextRequest) {
  const startedAt = Date.now();
  if (!isCronAuthorized(req)) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(req.url);
  const dateOverride = url.searchParams.get("date");
  const dateYmd = dateOverride && /^\d{4}-\d{2}-\d{2}$/.test(dateOverride) ? dateOverride : todayYmdJst();

  const editionParam = url.searchParams.get("edition")?.trim().toLowerCase();
  let edition: BlogEdition | undefined;
  if (editionParam === "evening_preview" || editionParam === "late_update") {
    edition = editionParam;
  } else if (editionParam) {
    return NextResponse.json(
      { ok: false, error: "invalid edition (use evening_preview | late_update)" },
      { status: 400 }
    );
  }

  const sourceParam = url.searchParams.get("source")?.trim();
  const pipelineSource: BlogDraftPipelineSource =
    sourceParam === "line_webhook" ||
    sourceParam === "vercel_cron" ||
    sourceParam === "github_actions_cron" ||
    sourceParam === "github_actions_retry" ||
    sourceParam === "manual_api"
      ? sourceParam
      : "github_actions_cron";

  const slug = parseRequestedStoreSlug(url);
  if (!slug) {
    return NextResponse.json(
      { ok: false, error: "missing required query param: store" },
      { status: 400 }
    );
  }
  const rangeLimit = cronRangeLimit();

  const results: Array<{
    slug: string;
    ok: boolean;
    duration_ms?: number;
    facts_id?: string;
    edition?: string;
    db?: { saved: boolean; id?: string; error?: string; skippedReason?: string };
    error?: string;
  }> = [];

  const perStoreStartedAt = Date.now();
  const store = getStoreMetaBySlugStrict(slug);
  if (!store) {
    results.push({
      slug,
      ok: false,
      duration_ms: Date.now() - perStoreStartedAt,
      error: `unknown store slug: ${slug}`,
    });
  } else {
    const factsId = buildStableFactsId(store.slug, dateYmd, edition, pipelineSource);
    const elapsedMs = Date.now() - startedAt;
    const remainingMs = REQUEST_BUDGET_MS - elapsedMs;
    if (remainingMs <= 0) {
      const timeoutMsg = `timeout risk before start (${elapsedMs}ms >= ${REQUEST_BUDGET_MS}ms budget)`;
      if (isBlogDraftsConfigured()) {
        await insertBlogDraft({
          store_id: store.storeId,
          store_slug: store.slug,
          target_date: dateYmd,
          facts_id: factsId,
          mdx_content: "",
          insight_json: {},
          source: pipelineSource,
          line_user_id: null,
          error_message: timeoutMsg,
        });
      }
      results.push({
        slug,
        ok: false,
        duration_ms: Date.now() - perStoreStartedAt,
        facts_id: factsId,
        error: timeoutMsg,
      });
    } else {
      let out: Awaited<ReturnType<typeof runBlogDraftPipeline>> | null = null;
      try {
        const timeoutPromise = new Promise<never>((_, reject) => {
          setTimeout(() => reject(new Error(`timeout risk (${REQUEST_BUDGET_MS}ms budget exceeded)`)), remainingMs);
        });
        out = (await Promise.race([
          runBlogDraftPipeline({
            backendUrl: BACKEND_URL,
            rangeLimit,
            store,
            dateYmd,
            factsId,
            topicHint: "",
            edition,
            source: pipelineSource,
            lineUserId: null,
          }),
          timeoutPromise,
        ])) as Awaited<ReturnType<typeof runBlogDraftPipeline>>;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (isBlogDraftsConfigured()) {
          await insertBlogDraft({
            store_id: store.storeId,
            store_slug: store.slug,
            target_date: dateYmd,
            facts_id: factsId,
            mdx_content: "",
            insight_json: {},
            source: pipelineSource,
            line_user_id: null,
            error_message: msg,
          });
        }
        results.push({
          slug,
          ok: false,
          duration_ms: Date.now() - perStoreStartedAt,
          facts_id: factsId,
          error: msg,
        });
        out = null;
      }
      if (!out) {
        // timeout/error path already recorded above
      } else if (!out.ok) {
        results.push({
          slug,
          ok: false,
          duration_ms: Date.now() - perStoreStartedAt,
          facts_id: out.factsId,
          error: out.error,
        });
      } else {
        results.push({
          slug,
          ok: true,
          duration_ms: Date.now() - perStoreStartedAt,
          facts_id: out.factsId,
          edition: out.insightResult.draft_context.edition,
          db: out.db,
        });
      }
    }
  }

  const allOk = results.every((r) => r.ok);
  const durationMs = Date.now() - startedAt;
  const nearTimeout = durationMs >= 50_000;
  const payload = {
    ok: allOk,
    service: "cron-blog-draft",
    duration_ms: durationMs,
    near_timeout: nearTimeout,
    dateYmd,
    rangeLimit,
    edition_requested: edition ?? null,
    edition_inferred: results.find((r) => r.edition)?.edition,
    source: pipelineSource,
    results,
  };
  if (allOk) return NextResponse.json(payload);
  const isTimeout = results.some((r) => (r.error ?? "").toLowerCase().includes("timeout"));
  return NextResponse.json(payload, { status: isTimeout ? 504 : 500 });
}
