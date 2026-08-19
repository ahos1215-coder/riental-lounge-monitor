import { describe, expect, it, vi } from "vitest";
import type { Metadata } from "next";

/**
 * 番犬テスト（D-05）: 全ページの metadata / generateMetadata の最終出力をダンプし、
 * SEO ヘルパー（lib/seo/pageMetadata.ts）への置換前後で 1 文字も変わらないことを固定する。
 *
 * ダンプ時に URL インスタンスは `.href` へ正規化する。Next は openGraph.url に string と URL の
 * どちらを渡しても同じ絶対 URL へ解決するため、この2つは出力上等価（型の違いは HTML に出ない）。
 */

vi.mock("server-only", () => ({}));

// Supabase 依存（daily / weekly / blog editorial）は固定データに差し替える。
// generateMetadata は行が無いと notFound() を投げるため、必ず 1 行返す。
vi.mock("@/lib/supabase/blogDrafts", () => ({
  fetchLatestPublishedReportByStore: vi.fn(async () => ({
    id: "row-1",
    store_slug: "shibuya",
    mdx_content: "---\ntitle: x\n---\n# 見出し\n\n本文です。",
    facts_id: null,
    insight_json: {},
    target_date: "2026-08-18",
    created_at: "2026-08-18T09:00:00Z",
  })),
  // blog は「editorial あり」と「filesystem のみ」の両分岐を撮りたいので slug で切り替える。
  fetchPublishedEditorialBySlug: vi.fn(async (slug: string) =>
    slug === "__editorial__"
      ? {
          id: "ed-1",
          store_slug: "shibuya",
          public_slug: "__editorial__",
          mdx_content: "---\ntitle: y\n---\n## 編集記事の見出し\n\n編集記事の最初の段落です。",
          created_at: "2026-08-18T09:00:00Z",
        }
      : null,
  ),
}));

type Dumpable = unknown;

/** URL → href に正規化しつつ、undefined キーを落とした純 JSON へ落とす。 */
function normalize(value: Dumpable): Dumpable {
  if (value instanceof URL) return value.href;
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    const out: Record<string, Dumpable> = {};
    for (const [k, v] of Object.entries(value as Record<string, Dumpable>)) {
      if (v === undefined) continue;
      out[k] = normalize(v);
    }
    return out;
  }
  return value;
}

async function dumpAll(): Promise<Record<string, Dumpable>> {
  const { STORES } = await import("@/app/config/stores");
  const { AREAS } = await import("@/app/config/areas");

  const out: Record<string, Dumpable> = {};

  // --- 静的 metadata（export const metadata） ---
  const statics: Array<[string, string]> = [
    ["/", "@/app/page"],
    ["/stores", "@/app/stores/page"],
    ["/reports", "@/app/reports/page"],
    ["/mypage", "@/app/mypage/page"],
    ["/compare", "@/app/compare/page"],
  ];
  for (const [key, mod] of statics) {
    const m = (await import(/* @vite-ignore */ mod)) as { metadata: Metadata };
    out[key] = normalize(m.metadata);
  }

  // --- store/[id]（42店） ---
  {
    const { generateMetadata } = await import("@/app/store/[id]/page");
    for (const s of STORES) {
      out[`/store/${s.slug}`] = normalize(
        await generateMetadata({ params: Promise.resolve({ id: s.slug }) }),
      );
    }
  }

  // --- area/[area]（全エリア） ---
  {
    const { generateMetadata } = await import("@/app/area/[area]/page");
    for (const a of AREAS) {
      out[`/area/${a.id}`] = normalize(
        await generateMetadata({ params: Promise.resolve({ area: a.id }) }),
      );
    }
  }

  // --- reports/daily・weekly（代表2店で形を固定） ---
  {
    const daily = await import("@/app/reports/daily/[store_slug]/page");
    const weekly = await import("@/app/reports/weekly/[store_slug]/page");
    for (const slug of ["shibuya", "ay_chiba"]) {
      out[`/reports/daily/${slug}`] = normalize(
        await daily.generateMetadata({ params: Promise.resolve({ store_slug: slug }) }),
      );
      out[`/reports/weekly/${slug}`] = normalize(
        await weekly.generateMetadata({ params: Promise.resolve({ store_slug: slug }) }),
      );
    }
  }

  // --- blog/[slug]（editorial 1本 + filesystem 5本） ---
  {
    const { generateMetadata } = await import("@/app/blog/[slug]/page");
    const { getAllPostMetas } = await import("@/lib/blog/content");
    const slugs = ["__editorial__", ...getAllPostMetas().map((p) => p.slug)];
    for (const slug of slugs) {
      out[`/blog/${slug}`] = normalize(
        await generateMetadata({ params: Promise.resolve({ slug }) }),
      );
    }
  }

  return out;
}

describe("全ページの metadata 出力スナップショット（SEOヘルパー置換の番犬）", () => {
  it("title/description/canonical/OG/Twitter の最終出力が固定値と一致する", async () => {
    const dump = await dumpAll();
    await expect(JSON.stringify(dump, null, 1)).toMatchFileSnapshot(
      "./__snapshots__/pageMetadata.dump.json",
    );
    // 42店+全エリアの generateMetadata を直列で回すため、並列実行時は既定 5s を超えることがある。
  }, 30_000);

  it("店舗ページ42件・エリアページ全件をカバーしている", async () => {
    const dump = await dumpAll();
    const { STORES } = await import("@/app/config/stores");
    const { AREAS } = await import("@/app/config/areas");
    expect(Object.keys(dump).filter((k) => k.startsWith("/store/")).length).toBe(STORES.length);
    expect(Object.keys(dump).filter((k) => k.startsWith("/area/")).length).toBe(AREAS.length);
  }, 30_000);
});

describe("ページ固有の“例外”を意図として固定する（揃えると挙動が変わる箇所）", () => {
  it("blog は OG/Twitter title に「| めぐりび」を付けない（root layout の template は <title> のみに効く）", async () => {
    const { generateMetadata } = await import("@/app/blog/[slug]/page");
    const meta = await generateMetadata({ params: Promise.resolve({ slug: "__editorial__" }) });
    expect(meta.openGraph?.title).toBe(meta.title);
    expect(meta.twitter?.title).toBe(meta.title);
    expect(String(meta.openGraph?.title)).not.toContain("| めぐりび");
  });

  it("daily は noindex なので canonical を出さない", async () => {
    const { generateMetadata } = await import("@/app/reports/daily/[store_slug]/page");
    const meta = await generateMetadata({
      params: Promise.resolve({ store_slug: "shibuya" }),
    });
    expect(meta.alternates?.canonical).toBeUndefined();
    expect(meta.robots).toEqual({ index: false, follow: true });
  });

  it("compare / reports には twitter フィールドが無い（現状維持）", async () => {
    const compare = (await import("@/app/compare/page")) as { metadata: Metadata };
    const reports = (await import("@/app/reports/page")) as { metadata: Metadata };
    expect(compare.metadata.twitter).toBeUndefined();
    expect(reports.metadata.twitter).toBeUndefined();
  });

  it("mypage / compare には canonical が無い（現状維持）", async () => {
    const mypage = (await import("@/app/mypage/page")) as { metadata: Metadata };
    const compare = (await import("@/app/compare/page")) as { metadata: Metadata };
    expect(mypage.metadata.alternates?.canonical).toBeUndefined();
    expect(compare.metadata.alternates?.canonical).toBeUndefined();
  });

  it("トップ / reports は og:locale を持たない（他ページは ja_JP）", async () => {
    const root = (await import("@/app/page")) as { metadata: Metadata };
    const reports = (await import("@/app/reports/page")) as { metadata: Metadata };
    const stores = (await import("@/app/stores/page")) as { metadata: Metadata };
    expect(root.metadata.openGraph?.locale).toBeUndefined();
    expect(reports.metadata.openGraph?.locale).toBeUndefined();
    expect(stores.metadata.openGraph?.locale).toBe("ja_JP");
  });

  it("/stores の metadata は title/description/openGraph/twitter を自前で全部持つ（layout.tsx 不要の根拠）", async () => {
    const stores = (await import("@/app/stores/page")) as { metadata: Metadata };
    for (const key of ["title", "description", "openGraph", "twitter"] as const) {
      expect(stores.metadata[key], `stores/page.tsx に ${key} が無い`).toBeDefined();
    }
  });
});
