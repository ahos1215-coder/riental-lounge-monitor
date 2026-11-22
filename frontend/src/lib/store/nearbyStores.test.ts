import { describe, expect, it } from "vitest";
import { STORES, STORE_REGION_FILTER_ORDER, distanceKm, type StoreMeta } from "@/app/config/stores";
import { pickNearbyStores } from "./nearbyStores";

// StorePageClient の digestStores useMemo に元々あった実装をそのまま貼ったもの（番犬）。
function legacyPick(meta: StoreMeta): StoreMeta[] {
  const slug = meta.slug;
  const order = STORE_REGION_FILTER_ORDER;
  const curIdx = order.indexOf(meta.regionLabel);
  const regionDist = (region: string): number => {
    const i = order.indexOf(region);
    return curIdx < 0 || i < 0 ? 99 : Math.abs(i - curIdx);
  };
  return STORES.filter((s) => s.slug !== slug)
    .map((s, i) => {
      const km = distanceKm(meta, s);
      const p = km != null ? km : 100000 + regionDist(s.regionLabel);
      return { s, i, p };
    })
    .sort((a, b) => (a.p !== b.p ? a.p - b.p : a.i - b.i))
    .slice(0, 4)
    .map((x) => x.s);
}

describe("pickNearbyStores", () => {
  it("全店舗で旧実装と同じ結果（slug 順まで一致）", () => {
    for (const meta of STORES) {
      expect(pickNearbyStores(meta).map((s) => s.slug)).toEqual(legacyPick(meta).map((s) => s.slug));
    }
  });
  it("自店舗を含まず4件", () => {
    const r = pickNearbyStores(STORES[0]);
    expect(r).toHaveLength(4);
    expect(r.some((s) => s.slug === STORES[0].slug)).toBe(false);
  });
});
