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

/**
 * 番犬テスト（D-08 / C-03）: 各 GET 関数が実際に投げる URL・ヘッダ・キャッシュ指定を丸ごと固定する。
 * fetch ブロックを共通ヘルパー（restGetRows）へ寄せてもクエリ契約が 1 文字も変わらないことの担保。
 */
describe("Supabase REST GET の呼び出し契約（URL・ヘッダ・キャッシュ）", () => {
  const originalEnv = { ...process.env };
  let calls: Array<{ url: string; init: Record<string, unknown> }> = [];

  beforeEach(() => {
    calls = [];
    process.env.SUPABASE_URL = ENDPOINT_ENV.SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = ENDPOINT_ENV.SUPABASE_SERVICE_ROLE_KEY;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: Record<string, unknown>) => {
        calls.push({ url, init });
        return { ok: true, json: async () => [] } as unknown as Response;
      }),
    );
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  const EXPECTED_HEADERS = {
    apikey: "test-key",
    Authorization: "Bearer test-key",
    Accept: "application/json",
  };

  it.each([
    [
      "fetchLatestPublishedReportByStore",
      (m: typeof import("./blogDrafts")) => m.fetchLatestPublishedReportByStore("Shibuya", "weekly"),
      "https://proj.supabase.co/rest/v1/blog_drafts?select=facts_id,store_slug,target_date,mdx_content,insight_json,source,content_type,edition,public_slug,created_at,updated_at&store_slug=eq.shibuya&content_type=eq.weekly&is_published=eq.true&error_message=is.null&order=target_date.desc,updated_at.desc.nullslast,created_at.desc&limit=1",
      "no-store",
    ],
    [
      "fetchPublishedEditorialBySlug",
      (m: typeof import("./blogDrafts")) => m.fetchPublishedEditorialBySlug("My-Post"),
      "https://proj.supabase.co/rest/v1/blog_drafts?select=facts_id,public_slug,store_slug,target_date,mdx_content,insight_json,source,created_at&public_slug=eq.my-post&content_type=eq.editorial&is_published=eq.true&error_message=is.null&limit=1",
      "no-store",
    ],
    [
      "fetchAllPublishedEditorialSlugs",
      (m: typeof import("./blogDrafts")) => m.fetchAllPublishedEditorialSlugs(1000),
      "https://proj.supabase.co/rest/v1/blog_drafts?select=public_slug,target_date&content_type=eq.editorial&is_published=eq.true&error_message=is.null&public_slug=not.is.null&order=created_at.desc&limit=500",
      "no-store",
    ],
    [
      "fetchLatestUnpublishedEditorialByLineUser",
      (m: typeof import("./blogDrafts")) => m.fetchLatestUnpublishedEditorialByLineUser("U123"),
      "https://proj.supabase.co/rest/v1/blog_drafts?select=facts_id,public_slug,store_slug,target_date&line_user_id=eq.U123&content_type=eq.editorial&is_published=eq.false&error_message=is.null&mdx_content=not.eq.&order=created_at.desc&limit=1",
      "no-store",
    ],
  ])("%s の URL・ヘッダ・cache 指定が固定値と一致する", async (_name, call, expectedUrl, cache) => {
    const mod = await import("./blogDrafts");
    await call(mod);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(expectedUrl);
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.cache).toBe(cache);
    expect(calls[0].init.headers).toEqual(EXPECTED_HEADERS);
  });

  it("fetchAllLatestPublishedReports だけは no-store ではなく next.revalidate=300 を使う", async () => {
    const mod = await import("./blogDrafts");
    await mod.fetchAllLatestPublishedReports("daily", 1000);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      "https://proj.supabase.co/rest/v1/blog_drafts?select=store_slug,target_date,edition,created_at,mdx_content&content_type=eq.daily&is_published=eq.true&error_message=is.null&mdx_content=not.eq.&order=created_at.desc&limit=200",
    );
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.cache).toBeUndefined();
    expect(calls[0].init.next).toEqual({ revalidate: 300 });
    expect(calls[0].init.headers).toEqual(EXPECTED_HEADERS);
  });

  it("Supabase 未設定なら fetch を一度も呼ばない", async () => {
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    delete process.env.SUPABASE_SERVICE_KEY;
    const mod = await import("./blogDrafts");
    expect(await mod.fetchLatestPublishedReportByStore("shibuya", "daily")).toBeNull();
    expect(await mod.fetchAllPublishedEditorialSlugs()).toEqual([]);
    expect(await mod.fetchAllLatestPublishedReports("weekly")).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it("fetch が失敗（!ok / 非配列 / 例外）でも null / [] にフォールバックする", async () => {
    const mod = await import("./blogDrafts");

    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => [] }) as unknown as Response));
    expect(await mod.fetchLatestPublishedReportByStore("shibuya", "daily")).toBeNull();
    expect(await mod.fetchAllPublishedEditorialSlugs()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) }) as unknown as Response));
    expect(await mod.fetchPublishedEditorialBySlug("x")).toBeNull();
    expect(await mod.fetchAllLatestPublishedReports("daily")).toEqual([]);

    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("network down");
    }));
    expect(await mod.fetchLatestUnpublishedEditorialByLineUser("U1")).toBeNull();
    expect(await mod.fetchAllPublishedEditorialSlugs()).toEqual([]);
  });
});
