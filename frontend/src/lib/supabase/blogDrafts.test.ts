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
      "https://proj.supabase.co/rest/v1/blog_drafts?select=facts_id,store_slug,target_date,mdx_content,insight_json,source,content_type,edition,public_slug,created_at,updated_at&store_slug=eq.shibuya&content_type=eq.weekly&is_published=eq.true&error_message=is.null&order=target_date.desc,updated_at.desc.nullslast,created_at.desc,facts_id.desc&limit=1",
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
      "https://proj.supabase.co/rest/v1/blog_drafts?select=store_slug,target_date,edition,created_at,updated_at,mdx_content&content_type=eq.daily&is_published=eq.true&error_message=is.null&mdx_content=not.eq.&order=target_date.desc,updated_at.desc.nullslast,created_at.desc,facts_id.desc&limit=200",
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
    // 未設定は「0件」ではなく設定不備＝障害（F11）。
    expect(await mod.fetchAllLatestPublishedReports("weekly")).toEqual({ items: [], failed: true });
    expect(calls).toHaveLength(0);
  });

  it("fetch が失敗（!ok / 非配列 / 例外）でも null / [] にフォールバックする", async () => {
    const mod = await import("./blogDrafts");

    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => [] }) as unknown as Response));
    expect(await mod.fetchLatestPublishedReportByStore("shibuya", "daily")).toBeNull();
    expect(await mod.fetchAllPublishedEditorialSlugs()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) }) as unknown as Response));
    expect(await mod.fetchPublishedEditorialBySlug("x")).toBeNull();

    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("network down");
    }));
    expect(await mod.fetchLatestUnpublishedEditorialByLineUser("U1")).toBeNull();
    expect(await mod.fetchAllPublishedEditorialSlugs()).toEqual([]);
  });
});

/**
 * F6 / F11（2026-08-21 外部レビュー）の番犬テスト。
 *
 * F6-1: daily / weekly は固定 facts_id を PATCH し続けるため created_at は初回 INSERT 時刻で
 *       止まる。並びも表示も created_at では「8/20 の記事に 05/11 が併記される」。
 * F6-2: 取得上限 50 では daily の 42 店 × 2 便 ＝ 84 行を取り切れず、一部店舗が
 *       一覧に一生出てこない。
 * F11 : 取得失敗を [] にすると「本当に0件」と区別できない。
 */
describe("fetchAllLatestPublishedReports の並び・上限・障害の扱い（F6 / F11）", () => {
  const originalEnv = { ...process.env };
  let capturedUrl2 = "";

  function stubRows(rows: unknown, ok = true) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        capturedUrl2 = url;
        return { ok, json: async () => rows } as unknown as Response;
      }),
    );
  }

  beforeEach(() => {
    capturedUrl2 = "";
    process.env.SUPABASE_URL = ENDPOINT_ENV.SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = ENDPOINT_ENV.SUPABASE_SERVICE_ROLE_KEY;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("F6-1: 並びは target_date.desc が最優先で、created_at.desc 単独ではない", async () => {
    stubRows([]);
    const mod = await import("./blogDrafts");
    await mod.fetchAllLatestPublishedReports("daily");
    const order = decodeURIComponent(capturedUrl2).match(/order=([^&]+)/)?.[1] ?? "";
    expect(order.startsWith("target_date.desc")).toBe(true);
    expect(order).toContain("updated_at.desc.nullslast");
    expect(order).not.toBe("created_at.desc");
    // 単店取得（fetchLatestPublishedReportByStore）と同じ流儀に揃っていること。
    // 末尾の facts_id.desc は F6 の保険のタイブレーカー（外部レビュー F6・現象3）。
    expect(order).toBe("target_date.desc,updated_at.desc.nullslast,created_at.desc,facts_id.desc");
  });

  it("F6-1: select に updated_at を含む（カードの日時表示に使う）", async () => {
    stubRows([
      {
        store_slug: "shibuya",
        target_date: "2026-08-20",
        edition: "late_update",
        created_at: "2026-05-11T21:40:00+09:00",
        updated_at: "2026-08-20T21:40:00+09:00",
        mdx_content: "# 今夜の渋谷\n本文",
      },
    ]);
    const mod = await import("./blogDrafts");
    const res = await mod.fetchAllLatestPublishedReports("daily");
    expect(decodeURIComponent(capturedUrl2)).toContain("updated_at");
    expect(res.failed).toBe(false);
    expect(res.items[0].updated_at).toBe("2026-08-20T21:40:00+09:00");
    // created_at（初回 INSERT）も落とさない。表示側が updated_at を優先するだけ。
    expect(res.items[0].created_at).toBe("2026-05-11T21:40:00+09:00");
    expect(res.items[0].heading).toBe("今夜の渋谷");
  });

  it("F6-2: 既定の取得上限は 42店×2便＝84 行を上回る（一部店舗が一生出てこない状態にしない）", async () => {
    stubRows([]);
    const mod = await import("./blogDrafts");
    await mod.fetchAllLatestPublishedReports("daily");
    const limit = Number(decodeURIComponent(capturedUrl2).match(/limit=(\d+)/)?.[1] ?? "0");
    expect(limit).toBeGreaterThanOrEqual(84);
  });

  it("店舗ごとに先勝ちで1件へ畳む（並び順が新しい行を勝たせる前提）", async () => {
    stubRows([
      { store_slug: "shibuya", target_date: "2026-08-20", mdx_content: "# 新\n" },
      { store_slug: "shibuya", target_date: "2026-08-19", mdx_content: "# 旧\n" },
      { store_slug: "umeda", target_date: "2026-08-20", mdx_content: "# 梅田\n" },
    ]);
    const mod = await import("./blogDrafts");
    const res = await mod.fetchAllLatestPublishedReports("daily");
    expect(res.items.map((i) => i.store_slug)).toEqual(["shibuya", "umeda"]);
    expect(res.items[0].target_date).toBe("2026-08-20");
  });

  it("F11: HTTP エラー / 非配列 JSON / ネットワーク例外は failed:true（「0件」と区別する）", async () => {
    const mod = await import("./blogDrafts");

    stubRows([], false);
    expect(await mod.fetchAllLatestPublishedReports("daily")).toEqual({ items: [], failed: true });

    stubRows({});
    expect(await mod.fetchAllLatestPublishedReports("daily")).toEqual({ items: [], failed: true });

    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("network down");
    }));
    expect(await mod.fetchAllLatestPublishedReports("weekly")).toEqual({ items: [], failed: true });
  });

  it("F11: 本当に0件のときは failed:false（空表示と障害表示を取り違えない）", async () => {
    stubRows([]);
    const mod = await import("./blogDrafts");
    expect(await mod.fetchAllLatestPublishedReports("weekly")).toEqual({ items: [], failed: false });
  });
});

/**
 * 書き込み経路（PATCH / POST）の契約テスト。
 *
 * 背景（2026-08-19 取りこぼし監査）: ヘッダ組み立てを restHeaders(key, "write") に集約したが、
 * テストは GET 側しか無かった。LINE の editorial 承認（publishEditorial*）と日次/週次の
 * upsert は本番書き込みで、Prefer: return=representation が落ちると「更新できたのに
 * public_slug が取れず承認が失敗する」という静かな事故になる。ここで固定する。
 */
describe("Supabase REST 書き込みの呼び出し契約（method・Prefer・Content-Type・URL フィルタ）", () => {
  const originalEnv = { ...process.env };
  let calls: Array<{ url: string; init: Record<string, unknown> }> = [];

  const WRITE_HEADERS = {
    apikey: "test-key",
    Authorization: "Bearer test-key",
    "Content-Type": "application/json",
    Prefer: "return=representation",
  };

  function stubWriteFetch(responses: Array<{ ok: boolean; text: string }>) {
    let i = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: Record<string, unknown>) => {
        calls.push({ url, init });
        const r = responses[Math.min(i, responses.length - 1)];
        i += 1;
        return { ok: r.ok, status: r.ok ? 200 : 500, text: async () => r.text } as unknown as Response;
      }),
    );
  }

  beforeEach(() => {
    calls = [];
    process.env.SUPABASE_URL = ENDPOINT_ENV.SUPABASE_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = ENDPOINT_ENV.SUPABASE_SERVICE_ROLE_KEY;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("publishEditorialBySlug は public_slug + content_type=editorial で PATCH する", async () => {
    stubWriteFetch([{ ok: true, text: JSON.stringify([{ public_slug: "my-post" }]) }]);
    const mod = await import("./blogDrafts");
    const res = await mod.publishEditorialBySlug("my-post");

    expect(res).toEqual({ ok: true, publicSlug: "my-post" });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      "https://proj.supabase.co/rest/v1/blog_drafts?public_slug=eq.my-post&content_type=eq.editorial",
    );
    expect(calls[0].init.method).toBe("PATCH");
    expect(calls[0].init.headers).toEqual(WRITE_HEADERS);
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ is_published: true });
  });

  it("publishEditorialByFactsId は facts_id + content_type=editorial で PATCH し public_slug を返す", async () => {
    stubWriteFetch([{ ok: true, text: JSON.stringify([{ public_slug: "from-row" }]) }]);
    const mod = await import("./blogDrafts");
    const res = await mod.publishEditorialByFactsId("2026-08-19_shibuya_editorial");

    expect(res).toEqual({ ok: true, publicSlug: "from-row" });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      "https://proj.supabase.co/rest/v1/blog_drafts?facts_id=eq.2026-08-19_shibuya_editorial&content_type=eq.editorial",
    );
    expect(calls[0].init.method).toBe("PATCH");
    expect(calls[0].init.headers).toEqual(WRITE_HEADERS);
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ is_published: true });
  });

  it("insertBlogDraft は facts_id で PATCH → 空配列なら POST にフォールバックする", async () => {
    // 1回目(PATCH)は「該当行なし」の空配列、2回目(POST)で挿入される。
    stubWriteFetch([
      { ok: true, text: "[]" },
      { ok: true, text: JSON.stringify([{ id: "new-row" }]) },
    ]);
    const mod = await import("./blogDrafts");
    const res = await mod.insertBlogDraft({
      store_id: "ol_shibuya",
      store_slug: "shibuya",
      target_date: "2026-08-19",
      facts_id: "2026-08-19_shibuya_daily",
      mdx_content: "# 本文",
      insight_json: { a: 1 },
      source: "local_ollama",
      content_type: "daily",
      is_published: true,
    });

    expect(res).toEqual({ ok: true, id: "new-row" });
    expect(calls).toHaveLength(2);

    // PATCH: facts_id フィルタ付き
    expect(calls[0].url).toBe(
      "https://proj.supabase.co/rest/v1/blog_drafts?facts_id=eq.2026-08-19_shibuya_daily",
    );
    expect(calls[0].init.method).toBe("PATCH");
    expect(calls[0].init.headers).toEqual(WRITE_HEADERS);

    // POST: フィルタ無しのエンドポイントそのもの
    expect(calls[1].url).toBe("https://proj.supabase.co/rest/v1/blog_drafts");
    expect(calls[1].init.method).toBe("POST");
    expect(calls[1].init.headers).toEqual(WRITE_HEADERS);

    // 本文は PATCH / POST とも同一で、未指定キーは既定値で埋まる。
    const patchBody = JSON.parse(String(calls[0].init.body));
    expect(JSON.parse(String(calls[1].init.body))).toEqual(patchBody);
    expect(patchBody).toEqual({
      store_id: "ol_shibuya",
      store_slug: "shibuya",
      target_date: "2026-08-19",
      facts_id: "2026-08-19_shibuya_daily",
      mdx_content: "# 本文",
      insight_json: { a: 1 },
      source: "local_ollama",
      content_type: "daily",
      is_published: true,
      edition: null,
      public_slug: null,
      line_user_id: null,
      error_message: null,
    });
  });

  it("PATCH が既存行を返したら POST しない（固定 URL の上書き＝Freshness 優先）", async () => {
    stubWriteFetch([{ ok: true, text: JSON.stringify([{ id: "row-1" }]) }]);
    const mod = await import("./blogDrafts");
    const res = await mod.insertBlogDraft({
      store_id: "ol_shibuya",
      store_slug: "shibuya",
      target_date: "2026-08-19",
      facts_id: "2026-08-19_shibuya_daily",
      mdx_content: "# 本文",
      insight_json: {},
      source: "local_ollama",
    });
    expect(res).toEqual({ ok: true, id: "row-1" });
    expect(calls).toHaveLength(1);
    expect(calls[0].init.method).toBe("PATCH");
  });

  it("Supabase 未設定なら書き込み系は fetch せずエラーを返す", async () => {
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    delete process.env.SUPABASE_SERVICE_KEY;
    stubWriteFetch([{ ok: true, text: "[]" }]);
    const mod = await import("./blogDrafts");
    expect((await mod.publishEditorialBySlug("x")).ok).toBe(false);
    expect((await mod.publishEditorialByFactsId("y")).ok).toBe(false);
    expect(calls).toHaveLength(0);
  });
});
