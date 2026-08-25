import { describe, expect, it } from "vitest";

import { secondVenueClickParams } from "./SecondVenuesList";
import type { SecondVenue } from "../app/hooks/useSecondVenues";

// 2026-08-26 計測レビュー対応: second_venue_click（新設・従来クリック計測ゼロだった盲点）の
// パラメータ組み立てを純粋関数として切り出してテストする（vitest.config.ts は environment:"node"
// のためコンポーネントの実レンダーはできない。他ファイルの慣例 = 純粋関数を export してテストに合わせた）。
function makeLink(overrides: Partial<SecondVenue> = {}): SecondVenue {
  return {
    id: "shibuya-darts",
    purpose: "darts",
    label: "ダーツで二次会",
    description: "近くのダーツバーを Google マップで開きます。",
    url: "https://www.google.com/maps/search/?api=1&query=%E6%B8%8B%E8%B0%B7",
    serviceStyleHint: "unknown",
    ...overrides,
  };
}

describe("secondVenueClickParams", () => {
  it("店舗slug・venue_kind（purposeそのまま）・リンク先ホスト名を組み立てる", () => {
    expect(secondVenueClickParams("shibuya", makeLink())).toEqual({
      store_slug: "shibuya",
      venue_kind: "darts",
      destination_domain: "www.google.com",
    });
  });

  it("venue_kind は SecondVenuePurpose の実値をそのまま渡す（love_hotel はhotelに変換しない）", () => {
    // 指示書の想定値は "hotel" だったが、実際の型 SecondVenuePurpose には存在しない
    // （既存の正本 = love_hotel を使う。完了報告の「仕様から外れた点」参照）。
    const result = secondVenueClickParams("ebisu", makeLink({ purpose: "love_hotel" }));
    expect(result.venue_kind).toBe("love_hotel");
  });

  it("不正なURLでも例外を投げず空文字のdestination_domainを返す", () => {
    const result = secondVenueClickParams("shibuya", makeLink({ url: "not-a-url" }));
    expect(result.destination_domain).toBe("");
  });
});
