import {
  STORES,
  STORE_REGION_FILTER_ORDER,
  distanceKm,
  type StoreMeta,
} from "@/app/config/stores";

/**
 * 「今見ている店舗に地理的に近い」店を近い順に limit 件返す。
 * 実座標（stores.json の lat/lon）が全店に入ったので、ハバサイン距離で近い順に並べる。
 * 座標が欠けた店だけは地域（regionLabel）の並び順で近似し、距離が取れる店の後ろに置く。
 * （StorePageClient の digestStores から移設。同距離は元の並び順で安定）
 */
export function pickNearbyStores(
  meta: StoreMeta,
  stores: readonly StoreMeta[] = STORES,
  limit = 4,
): StoreMeta[] {
  const order = STORE_REGION_FILTER_ORDER;
  const curIdx = order.indexOf(meta.regionLabel);
  const regionDist = (region: string): number => {
    const i = order.indexOf(region);
    return curIdx < 0 || i < 0 ? 99 : Math.abs(i - curIdx);
  };
  return stores
    .filter((s) => s.slug !== meta.slug)
    .map((s, i) => {
      const km = distanceKm(meta, s);
      const p = km != null ? km : 100000 + regionDist(s.regionLabel);
      return { s, i, p };
    })
    .sort((a, b) => (a.p !== b.p ? a.p - b.p : a.i - b.i))
    .slice(0, limit)
    .map((x) => x.s);
}
