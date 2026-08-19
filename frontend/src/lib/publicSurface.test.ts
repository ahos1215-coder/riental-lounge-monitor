// frontend/src/lib/publicSurface.test.ts
//
// C-10（未参照エクスポートの撤去）の番犬テスト。
// 撤去してよいのは「参照ゼロの死蔵 export」だけで、実際に使われている export を
// 巻き込んで消していないことをここで固定する。撤去の前後どちらでも緑であること。
import { describe, expect, it } from "vitest";

import * as dateFormat from "@/lib/dateFormat";
import * as storesConfig from "@/app/config/stores";
import * as blogContent from "@/lib/blog/content";

describe("dateFormat の生きている export は残っている", () => {
  const LIVE = [
    "jstNightSessionDate",
    "formatJstMonthDay",
    "formatJstTimestamp",
    "formatJstLabel",
    "formatWindowTime",
  ] as const;

  for (const name of LIVE) {
    it(`${name} が export されている`, () => {
      expect(typeof (dateFormat as Record<string, unknown>)[name]).toBe("function");
    });
  }

  it("代表的な出力が変わっていない", () => {
    expect(dateFormat.formatJstMonthDay("2026-08-19")).toBe("8/19");
    expect(dateFormat.formatJstLabel("2026-08-19T22:33:00+09:00")).toBe("2026/08/19 22:33");
    expect(dateFormat.jstNightSessionDate(new Date("2026-08-20T03:00:00+09:00"))).toBe("2026-08-19");
  });
});

describe("app/config/stores の生きている export は残っている", () => {
  const LIVE = [
    "STORES",
    "DEFAULT_STORE",
    "getStoreMetaBySlugOrDefault",
    "getStoreMetaBySlugStrict",
    "isPercentCrowdBrand",
    "seatFullnessPercent",
  ] as const;

  for (const name of LIVE) {
    it(`${name} が export されている`, () => {
      expect((storesConfig as Record<string, unknown>)[name]).toBeDefined();
    });
  }

  it("slug 解決が従来どおり動く", () => {
    expect(storesConfig.getStoreMetaBySlugStrict("no-such-store")).toBeNull();
    expect(storesConfig.getStoreMetaBySlugOrDefault(null).slug).toBe(storesConfig.DEFAULT_STORE);
  });
});

describe("facts の読み口は publicFacts に一本化されている", () => {
  it("blog/content からは facts を読まない（getFactsById は撤去済み・二重窓口を作らない）", () => {
    expect((blogContent as Record<string, unknown>).getFactsById).toBeUndefined();
  });

  // publicFacts.ts は "server-only" を import するため vitest から直接読めない。
  // 生きている読み口が publicFacts 側にあることはソース上の grep で確認済み。

  it("blog/content の記事系 export は残っている", () => {
    expect(typeof blogContent.getAllPostMetas).toBe("function");
    expect(typeof blogContent.getPostBySlug).toBe("function");
  });
});
