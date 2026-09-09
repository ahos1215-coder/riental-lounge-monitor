// 番犬テスト: proxy がレポート URL を 404 へ rewrite するのは「本当に無い」ときだけ。
//
// 2026-09-09（Supabase 402）: proxy の存在確認は「行が無い」と「見に行けていない」を
// どちらも false に潰していたため、障害中は実在する 84 本のレポート URL がすべて
// /__not_found__ へ rewrite され、本物の 404 として CDN に載った（復旧後も残り、
// Search Console にクロールエラーが積み上がる）。ページ側の「一時的に取得できません」に
// 到達させるには、この手前の関門を fail-open にしておく必要がある。
import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  row: null as Record<string, unknown> | null,
  failed: false,
  /** Supabase の存在確認を実際に呼んだ回数（vi.fn は resetModules で作り直されるため自前で数える）。 */
  lookups: 0,
}));

vi.mock("@/lib/supabase/blogDrafts", () => ({
  fetchLatestPublishedReportByStoreWithStatus: vi.fn(async () => {
    state.lookups += 1;
    return { row: state.row, failed: state.failed };
  }),
  fetchPublishedEditorialBySlug: vi.fn(async () => null),
}));

async function runProxy(path: string): Promise<Response> {
  vi.resetModules();
  const { NextRequest } = await import("next/server");
  const { proxy } = await import("./proxy");
  return proxy(new NextRequest(new URL(`https://megribi.test${path}`)));
}

/** notFoundRewrite は /__not_found__ への rewrite（Next が 404 を返す内部パス）。 */
function rewrittenTo(res: Response): string | null {
  return res.headers.get("x-middleware-rewrite");
}

describe.each(["daily", "weekly"] as const)("proxy: /reports/%s/[store_slug]", (kind) => {
  it("取得に失敗した（failed）ときは 404 へ rewrite せずページに通す", async () => {
    state.row = null;
    state.failed = true;
    const res = await runProxy(`/reports/${kind}/shibuya`);
    expect(rewrittenTo(res)).toBeNull();
  });

  it("取得できたうえで 0 件のときは従来どおり 404 へ rewrite する", async () => {
    state.row = null;
    state.failed = false;
    const res = await runProxy(`/reports/${kind}/shibuya`);
    expect(rewrittenTo(res)).toContain("__not_found__");
  });

  it("行があるときは従来どおり通す", async () => {
    state.row = { facts_id: "f1", store_slug: "shibuya" };
    state.failed = false;
    const res = await runProxy(`/reports/${kind}/shibuya`);
    expect(rewrittenTo(res)).toBeNull();
  });
});

/**
 * 番犬テスト: fail-open の対象を「店舗マスタに実在する slug」に限ること。
 *
 * ページ側の notFound() は soft-404（HTTP 200）になり、app/not-found.tsx が無いので
 * layout.tsx の robots{index:true} を継承する。slug を選ばず fail-open すると、
 * 障害中は /reports/daily/<任意文字列> が「インデックス可能な 200」で無限に返り、
 * ゴミ URL が登録されうる。マスタ照合は stores.json を読むだけなので障害中でも効く。
 */
describe.each(["daily", "weekly"] as const)(
  "proxy: /reports/%s/[store_slug] の店舗マスタ検証",
  (kind) => {
    it("マスタに無い slug は取得失敗中でも 404 へ倒す（fail-open させない）", async () => {
      state.row = null;
      state.failed = true;
      const res = await runProxy(`/reports/${kind}/not-a-real-store-xyz`);
      expect(rewrittenTo(res)).toContain("__not_found__");
    });

    it("マスタに無い slug は Supabase を引かずに 404 へ倒す（コスト増ゼロ）", async () => {
      state.row = { facts_id: "f1", store_slug: "not-a-real-store-xyz" };
      state.failed = false;
      state.lookups = 0;
      const res = await runProxy(`/reports/${kind}/not-a-real-store-xyz`);
      expect(rewrittenTo(res)).toContain("__not_found__");
      expect(state.lookups).toBe(0);
    });

    it("閉店して stores.json から消えた slug も 404（soft-404 の 200 にしない）", async () => {
      state.row = null;
      state.failed = true;
      const res = await runProxy(`/reports/${kind}/sapporo_ag`);
      expect(rewrittenTo(res)).toContain("__not_found__");
    });

    it("マスタにある slug は従来どおり Supabase まで見に行って fail-open する", async () => {
      state.row = null;
      state.failed = true;
      state.lookups = 0;
      const res = await runProxy(`/reports/${kind}/shibuya`);
      expect(rewrittenTo(res)).toBeNull();
      expect(state.lookups).toBe(1);
    });

    it("大文字・前後空白つきでもマスタ照合できる（正常時の実在 URL を壊さない）", async () => {
      state.row = { facts_id: "f1", store_slug: "shibuya" };
      state.failed = false;
      const res = await runProxy(`/reports/${kind}/${encodeURIComponent(" Shibuya ")}`);
      expect(rewrittenTo(res)).toBeNull();
    });
  },
);
