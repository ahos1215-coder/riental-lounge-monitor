// 番犬テスト: レポートページが「取得できていないだけ」で 404 を返さないこと。
//
// 2026-09-09（Supabase 402）: /reports/daily/[store_slug] と /reports/weekly/[store_slug] は
// 行が取れないと一律 notFound() を呼んでいた。障害中は実在する 84 本のレポート URL が
// 404 を返し、404 は CDN に HIT で載るため復旧後もしばらく残り、Search Console にも
// クロールエラーが積み上がった。「本当に無い（0 件）」ときだけ 404 にする。
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  row: null as Record<string, unknown> | null,
  failed: false,
}));

vi.mock("server-only", () => ({}));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

vi.mock("@/lib/supabase/blogDrafts", () => ({
  fetchLatestPublishedReportByStoreWithStatus: vi.fn(async () => ({
    row: state.row,
    failed: state.failed,
  })),
}));

const GOOD_ROW = {
  facts_id: "",
  store_slug: "shibuya",
  target_date: "2026-09-08",
  mdx_content: "# 見出し\n\n本文です。",
  insight_json: {},
  source: "ollama",
  content_type: "daily" as const,
  created_at: "2026-09-08T09:00:00Z",
  updated_at: "2026-09-08T12:00:00Z",
};

const params = Promise.resolve({ store_slug: "shibuya" });

type PageModule = {
  default: (props: { params: Promise<{ store_slug: string }> }) => Promise<{
    type: unknown;
    props: Record<string, unknown>;
  }>;
  generateMetadata: (props: { params: Promise<{ store_slug: string }> }) => Promise<{
    robots?: unknown;
  }>;
};

/**
 * ページを毎回まっさらな module registry で読み込む（React cache() のメモ化を跨がせない）。
 * 「一時的に取得できません」コンポーネントも同じ世代のものを返さないと、参照比較が
 * 別インスタンス同士になって一致しないため一緒に読み直す。
 */
async function loadPage(
  kind: "daily" | "weekly",
): Promise<{ page: PageModule; Unavailable: unknown }> {
  vi.resetModules();
  const mod =
    kind === "daily"
      ? await import("./daily/[store_slug]/page")
      : await import("./weekly/[store_slug]/page");
  const { ReportTemporarilyUnavailable } = await import(
    "@/components/reports/ReportTemporarilyUnavailable"
  );
  return { page: mod as unknown as PageModule, Unavailable: ReportTemporarilyUnavailable };
}

describe.each(["daily", "weekly"] as const)("/reports/%s/[store_slug]", (kind) => {
  beforeEach(() => {
    state.row = null;
    state.failed = false;
  });

  it("取得に失敗したときは notFound() を呼ばず「一時的に取得できません」を返す", async () => {
    state.row = null;
    state.failed = true;
    const { page, Unavailable } = await loadPage(kind);
    const el = await page.default({ params });
    expect(el.type).toBe(Unavailable);
    expect(el.props).toMatchObject({ storeSlug: "shibuya", reportType: kind });
  });

  it("取得に失敗したときは generateMetadata も 404 にしない（noindex は維持）", async () => {
    state.row = null;
    state.failed = true;
    const { page } = await loadPage(kind);
    const meta = await page.generateMetadata({ params });
    expect(meta.robots).toEqual({ index: false, follow: true });
  });

  it("取得できたうえで 0 件のときだけ 404（存在しないレポートは従来どおり）", async () => {
    state.row = null;
    state.failed = false;
    const { page } = await loadPage(kind);
    await expect(page.default({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(page.generateMetadata({ params })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("正常時は従来どおりレポート本体を返す", async () => {
    state.row = { ...GOOD_ROW, content_type: kind };
    state.failed = false;
    const { page, Unavailable } = await loadPage(kind);
    const el = await page.default({ params });
    expect(el.type).not.toBe(Unavailable);
    expect(el.type).toBe("main");
    expect(el.props["data-report-state"]).toBeUndefined();
  });
});
