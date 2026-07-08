import { describe, expect, it } from "vitest";

import { buildBreadcrumbList, buildNightClubJsonLd, serializeJsonLd } from "./jsonLd";

describe("serializeJsonLd", () => {
  it("escapes '<' to prevent </script> breakout", () => {
    const out = serializeJsonLd({ name: "</script><script>alert(1)</script>" });
    expect(out).not.toContain("</script>");
    expect(out).toContain("\\u003c/script>");
  });
});

describe("buildBreadcrumbList", () => {
  it("auto-numbers position from array order", () => {
    const bc = buildBreadcrumbList([
      { name: "ホーム", item: "https://www.meguribi.jp/" },
      { name: "店舗一覧", item: "https://www.meguribi.jp/stores" },
    ]);
    expect(bc["@type"]).toBe("BreadcrumbList");
    expect(bc.itemListElement).toEqual([
      { "@type": "ListItem", position: 1, name: "ホーム", item: "https://www.meguribi.jp/" },
      { "@type": "ListItem", position: 2, name: "店舗一覧", item: "https://www.meguribi.jp/stores" },
    ]);
  });
});

describe("buildNightClubJsonLd", () => {
  it("defaults addressCountry to JP for domestic stores", () => {
    const ld = buildNightClubJsonLd({
      name: "オリエンタルラウンジ 渋谷本店",
      url: "https://www.meguribi.jp/store/shibuya",
      regionLabel: "関東",
      areaLabel: "渋谷",
      lat: 35.6595,
      lon: 139.7005,
    });
    const address = ld.address as Record<string, unknown>;
    expect(address.addressCountry).toBe("JP");
    expect(ld.geo).toEqual({
      "@type": "GeoCoordinates",
      latitude: 35.6595,
      longitude: 139.7005,
    });
  });

  it("infers addressCountry KR for the gangnam (Seoul) overseas store", () => {
    const ld = buildNightClubJsonLd({
      name: "オリエンタルラウンジ ソウル カンナム",
      url: "https://www.meguribi.jp/store/gangnam",
      regionLabel: "海外",
      areaLabel: "韓国・江南",
      lat: 37.500488,
      lon: 127.025305,
    });
    const address = ld.address as Record<string, unknown>;
    expect(address.addressCountry).toBe("KR");
    expect(ld["@type"]).toBe("NightClub");
  });

  it("omits geo when lat/lon are not provided", () => {
    const ld = buildNightClubJsonLd({
      name: "テスト店舗",
      url: "https://www.meguribi.jp/store/test",
      regionLabel: "関東",
      areaLabel: "テスト",
    });
    expect(ld.geo).toBeUndefined();
  });
});
