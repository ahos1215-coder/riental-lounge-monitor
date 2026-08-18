import { describe, expect, it } from "vitest";

import { STORES } from "../../config/stores";
import { generateMetadata } from "./page";

/**
 * ブランド憲法（CLAUDE.md / オーナー指示）の機械検証:
 *   - brand=oriental の生成メタ文字列に「相席屋」が1文字も出てはいけない
 *   - brand=aisekiya の生成メタ文字列に「オリエンタルラウンジ」が1文字も出てはいけない
 * 「相席ラウンジ」「相席」は両ブランド共通の一般語として許可（禁止語チェックの対象外）。
 *
 * 42店舗（オリエンタル37 + 相席屋5）全件を実際に generateMetadata に通してダンプし、
 * title/description/openGraph/twitter の全フィールドを対象にする。
 */
describe("store/[id] generateMetadata — brand safety", () => {
  it("covers all 42 stores (37 oriental + 5 aisekiya)", () => {
    expect(STORES.length).toBe(42);
    expect(STORES.filter((s) => s.brand === "oriental").length).toBe(37);
    expect(STORES.filter((s) => s.brand === "aisekiya").length).toBe(5);
  });

  it.each(STORES.map((s) => [s.slug, s.brand] as const))(
    "%s (%s): never leaks the other brand's name across title/description/OG/Twitter",
    async (slug, brand) => {
      const meta = await generateMetadata({ params: Promise.resolve({ id: slug }) });
      const forbidden = brand === "oriental" ? "相席屋" : "オリエンタルラウンジ";

      const haystacks: Array<[string, string | null | undefined]> = [
        ["title", typeof meta.title === "string" ? meta.title : null],
        ["description", meta.description],
        [
          "openGraph.title",
          typeof meta.openGraph?.title === "string" ? meta.openGraph.title : null,
        ],
        ["openGraph.description", meta.openGraph?.description as string | undefined],
        [
          "twitter.title",
          typeof meta.twitter?.title === "string" ? meta.twitter.title : null,
        ],
        ["twitter.description", meta.twitter?.description as string | undefined],
      ];

      for (const [field, value] of haystacks) {
        if (!value) continue;
        expect(value, `${slug} ${field} leaked "${forbidden}"`).not.toContain(forbidden);
      }
    },
  );

  it("dumps title length (zenkaku-count) per store for manual mobile-SERP review", async () => {
    const rows = await Promise.all(
      STORES.map(async (s) => {
        const meta = await generateMetadata({ params: Promise.resolve({ id: s.slug }) });
        const title = typeof meta.title === "string" ? meta.title : "";
        return { slug: s.slug, brand: s.brand, length: title.length, title };
      }),
    );
    // eslint-disable-next-line no-console
    console.table(rows);
    // 回帰ガード: <title>本文（"| めぐりび" テンプレ付与前）が極端に長くならないこと。
    // モバイルSERPは実質30〜35字で切れるため、余裕を見て上限40字とする。
    for (const row of rows) {
      expect(row.length, `${row.slug} title too long for mobile SERP: "${row.title}"`).toBeLessThanOrEqual(
        40,
      );
    }
  });
});
