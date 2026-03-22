import type { StoreMeta } from "@/app/config/stores";
import { buildInsightFromBackend, type InsightBuildResult } from "./insightFromRange";
import { generateBlogDraftMdx } from "./draftGenerator";
import { insertBlogDraft, isBlogDraftsConfigured } from "@/lib/supabase/blogDrafts";

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 20)}\n…(省略)`;
}

export type BlogDraftPipelineSource = "line_webhook" | "vercel_cron" | "manual_api";

export type RunBlogDraftPipelineInput = {
  backendUrl: string;
  rangeLimit: number;
  store: StoreMeta;
  dateYmd: string;
  factsId: string;
  topicHint?: string;
  source: BlogDraftPipelineSource;
  lineUserId?: string | null;
};

export type RunBlogDraftPipelineOk = {
  ok: true;
  factsId: string;
  mdx: string;
  insightResult: InsightBuildResult;
  /** LINE 返信用の要約行 */
  summaryLines: string[];
  db: { saved: boolean; id?: string; error?: string; skippedReason?: string };
};

export type RunBlogDraftPipelineErr = {
  ok: false;
  error: string;
  factsId?: string;
};

export async function runBlogDraftPipeline(
  input: RunBlogDraftPipelineInput
): Promise<RunBlogDraftPipelineOk | RunBlogDraftPipelineErr> {
  const { backendUrl, rangeLimit, store, dateYmd, factsId, topicHint, source, lineUserId } = input;

  try {
    const insightResult = await buildInsightFromBackend(backendUrl, store.slug, dateYmd, rangeLimit);

    const mdx = await generateBlogDraftMdx({
      storeLabel: store.label,
      storeSlug: store.slug,
      dateYmd,
      factsId,
      insightResult,
      topicHint: topicHint ?? "",
    });

    const insightPayload = {
      facts_id: factsId,
      store: store.slug,
      range: insightResult.range,
      insight: insightResult.insight,
      quality_flags: insightResult.quality_flags,
      source: insightResult.source,
      shift: insightResult.shift,
      draft_context: insightResult.draft_context,
    };

    let db: RunBlogDraftPipelineOk["db"];
    if (isBlogDraftsConfigured()) {
      const ins = await insertBlogDraft({
        store_id: store.storeId,
        store_slug: store.slug,
        target_date: dateYmd,
        facts_id: factsId,
        mdx_content: mdx,
        insight_json: insightPayload as unknown as Record<string, unknown>,
        source,
        line_user_id: lineUserId ?? null,
        error_message: null,
      });
      if (ins.ok) {
        db = { saved: true, id: ins.id };
      } else {
        db = { saved: false, error: ins.error };
      }
    } else {
      db = { saved: false, skippedReason: "Supabase 未設定のためDBには保存していません（GEMINIのみ生成）。" };
    }

    let dbNote = "";
    if (db.saved && db.id) dbNote = `\n保存ID: ${db.id}`;
    else if ("error" in db && db.error) dbNote = `\n※DB保存スキップ: ${db.error}`;
    else if ("skippedReason" in db && db.skippedReason) dbNote = `\n※${db.skippedReason}`;

    const summaryLines = [
      `下書きを生成しました（${store.label} / ${dateYmd}）`,
      `facts_id: ${factsId}`,
      `混雑: ${insightResult.insight.crowd_label || "—"} / ピーク ${insightResult.insight.peak_time || "—"} / 狙い目(入店しやすさ目安) ${insightResult.insight.avoid_time || "—"} / 便:${insightResult.draft_context.edition}`,
      `データ: ${insightResult.source} shift=${insightResult.shift}${dbNote}`,
      "",
      "---- MDX（冒頭）----",
      truncate(mdx, 3500),
    ];

    return {
      ok: true,
      factsId,
      mdx,
      insightResult,
      summaryLines,
      db,
    };
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
        source,
        line_user_id: lineUserId ?? null,
        error_message: msg,
      });
    }

    return { ok: false, error: msg, factsId };
  }
}
