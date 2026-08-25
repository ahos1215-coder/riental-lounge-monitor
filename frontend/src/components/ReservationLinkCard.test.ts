import { describe, expect, it } from "vitest";

import { officialSiteClickParams } from "./ReservationLinkCard";

// 2026-08-26 計測レビュー対応: official_site_click（新設・従来クリック計測ゼロだった盲点）の
// パラメータ組み立てを純粋関数として切り出してテストする（vitest.config.ts は environment:"node"
// のためコンポーネントの実レンダーはできない。他ファイルの慣例 = 純粋関数を export してテストに合わせた）。
describe("officialSiteClickParams", () => {
  it("店舗slug・ブランド・リンク先ホスト名を組み立てる", () => {
    expect(
      officialSiteClickParams("shibuya", "oriental", "https://oriental-lounge.com/"),
    ).toEqual({
      store_slug: "shibuya",
      brand: "oriental",
      destination_domain: "oriental-lounge.com",
    });
  });

  it("UTM付与前のベースURLからホスト名だけを取り出す（クエリ文字列は含めない）", () => {
    const result = officialSiteClickParams(
      "ay_chiba",
      "aisekiya",
      "https://aiseki-ya.com/stores/chiba/?foo=bar",
    );
    expect(result.destination_domain).toBe("aiseki-ya.com");
    expect(result.destination_domain).not.toContain("?");
  });

  it("brand=jis は oriental にフォールバックする（analytics.ts の brand 型は2値のみのため）", () => {
    const result = officialSiteClickParams("some_jis_store", "jis", "https://oriental-lounge.com/");
    expect(result.brand).toBe("oriental");
  });
});
