/**
 * fetchLatestPublishedReportByStore の Supabase クエリ契約テスト。
 *
 * 背景（2026-08-19 監査・所見1）:
 *   日次レポートの生成に失敗した edition は、前回の良品の本文と target_date を
 *   そのまま書き戻す（scripts/local_report_job.py の _apply_carry_over_or_fail）。
 *   その行は「日付は古いまま updated_at だけが今」という形になるため、updated_at だけで
 *   並べると、今日成功したもう片方の edition より古い carry-over 行が勝ってしまう。
 *   ここでは order の先頭が target_date.desc であること（＝新しい日付の行を先に見る）と、
 *   「表示可能な良品」の絞り込み条件が変わっていないことを固定する。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ENDPOINT_ENV = { SUPABASE_URL: "https://proj.supabase.co", SUPABASE_SERVICE_ROLE_KEY: "test-key" };

let capturedUrl = "";

function mockFetchReturning(rows: unknown) {
  return vi.fn(async (url: string) => {
    capturedUrl = url;
    return {
      ok: true,
      json: async () => rows,
    } as unknown as Response;
  });
}

describe("fetchLatestPublishedReportByStore のクエリ契約", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    capturedUrl = "";
    process.env.SUPABASE_URL = ENDPOINT_ENV.SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = ENDPOINT_ENV.SUPABASE_SERVICE_ROLE_KEY;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function callOnce(rows: unknown) {
    vi.stubGlobal("fetch", mockFetchReturning(rows));
    const mod = await import("./blogDrafts");
    return mod.fetchLatestPublishedReportByStore("shibuya", "daily");
  }

  it("target_date.desc を最優先に並べる（carry-over 行が今日の成功行に勝たないこと）", async () => {
    await callOnce([]);
    const order = decodeURIComponent(capturedUrl).match(/order=([^&]+)/)?.[1] ?? "";
    expect(order.startsWith("target_date.desc")).toBe(true);
    // 既存のタイブレークは維持する（同じ日付なら直近に再生成した edition を出す）。
    expect(order).toContain("updated_at.desc.nullslast");
    expect(order).toContain("created_at.desc");
  });

  it("「表示可能な良品」の絞り込み条件は is_published=true かつ error_message is null のまま", async () => {
    await callOnce([]);
    const url = decodeURIComponent(capturedUrl);
    expect(url).toContain("is_published=eq.true");
    expect(url).toContain("error_message=is.null");
    expect(url).toContain("content_type=eq.daily");
    expect(url).toContain("store_slug=eq.shibuya");
  });

  it("carry-over 行（error_message なし・古い target_date）はそのまま表示行として返る", async () => {
    const row = await callOnce([
      {
        facts_id: "auto_shibuya_late_update",
        store_slug: "shibuya",
        target_date: "2026-08-18",
        mdx_content: "# 昨夜のレポート\n本文",
        insight_json: { last_error: { message: "ollama generation failed" } },
        source: "local_gemma_daily",
        content_type: "daily",
        edition: "late_update",
        updated_at: "2026-08-19T12:30:00+09:00",
      },
    ]);

    expect(row).not.toBeNull();
    // 表示される日付は carry-over 元の日付（「今日の日付で前日の本文」にならない）。
    expect(row?.target_date).toBe("2026-08-18");
    expect(row?.mdx_content).toContain("昨夜のレポート");
  });
});
