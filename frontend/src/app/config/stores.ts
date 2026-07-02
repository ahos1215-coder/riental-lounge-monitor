import rawStores from "@/data/stores.json";

export type StoreOption = { value: string; label: string };

export type BrandId = "oriental" | "aisekiya" | "jis";

export type StoreMeta = {
  slug: string;
  storeId: string;
  label: string;
  areaLabel: string;
  regionLabel: string;
  mapsQueryBase: string;
  brand: BrandId;
  /** 相席屋のみ設定。席数(=(テーブル+VIP)×2)。%表示の逆算に使う。他ブランドは null。 */
  capacity: number | null;
  /** 店舗の緯度・経度（公式サイトの地図から取得）。おすすめ店舗の距離判定に使う。 */
  lat: number | null;
  lon: number | null;
};

/** 2地点間の距離(km)。ハバサイン公式。おすすめ店舗の「近い順」に使う。 */
export function distanceKm(
  a: { lat: number | null; lon: number | null },
  b: { lat: number | null; lon: number | null },
): number | null {
  if (a.lat == null || a.lon == null || b.lat == null || b.lon == null) return null;
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/**
 * 相席屋の席数（片性別あたり = (テーブル+VIP)×2）。相席屋の公式サイトは人数を出さず
 * 「席の埋まり具合(%)」だけを出しており、当プロジェクトでは `人数 = round(席数 × %/100)`
 * で逆算した推定人数を保存している。お客様向けには元データである%を表示するため、保存済み
 * の人数から `% = round(人数 / 席数 × 100)` で復元する。
 *
 * 席数の単一ソースは stores.json の各店 `capacity` フィールド（下の STORES で読み込む）。
 * 生の座席レイアウト(tables/vip)は multi_collect.py の AISEKIYA_STORES にあり、
 * tests/test_store_capacity_ssot.py が「(tables+vip)×2 == stores.json.capacity」を検証して
 * 両者のズレを検知する。店舗レイアウト変更時は multi_collect の tables/vip と stores.json の
 * capacity を更新すればよい（このファイルにハードコードは持たない）。
 */

/** 相席屋は人数非公開（%のみ）。お客様向け表示を%にするブランドかどうか。 */
export function isPercentCrowdBrand(brand: BrandId): boolean {
  return brand === "aisekiya";
}

/** 逆算推定の人数から「席の埋まり具合(%)」を復元。capacity が無ければ null。 */
export function seatFullnessPercent(
  count: number,
  capacity: number | null | undefined,
): number | null {
  if (!capacity || capacity <= 0) return null;
  const pct = Math.round((Math.max(0, count) / capacity) * 100);
  return Math.max(0, Math.min(100, pct));
}

/** ブランドの表示ラベル (StoreCard 等で使用) */
export const BRAND_DISPLAY_LABEL: Record<BrandId, string> = {
  oriental: "ORIENTAL LOUNGE",
  aisekiya: "相席屋",
  jis: "JIS",
};

/** 店舗名表示のフルネーム生成 (例: "オリエンタルラウンジ 渋谷本店") */
export function buildStoreFullName(meta: StoreMeta): string {
  if (meta.brand === "oriental") return `オリエンタルラウンジ ${meta.label}`;
  if (meta.brand === "aisekiya") return `相席屋 ${meta.label}`;
  if (meta.brand === "jis") return `JIS ${meta.label}`;
  return meta.label;
}

// Source of truth: frontend/src/data/stores.json (shared with Python backend)
export const STORES: StoreMeta[] = rawStores.map((s) => {
  const rawBrand = (s as { brand?: string }).brand ?? "oriental";
  const brand: BrandId =
    rawBrand === "aisekiya" ? "aisekiya" : rawBrand === "jis" ? "jis" : "oriental";
  return {
    slug: s.slug,
    storeId: s.store_id,
    label: s.label,
    areaLabel: s.area_label,
    regionLabel: s.region_label,
    mapsQueryBase: s.maps_query_base,
    brand,
    capacity:
      brand === "aisekiya" && typeof (s as { capacity?: number }).capacity === "number"
        ? (s as { capacity: number }).capacity
        : null,
    lat: typeof (s as { lat?: number }).lat === "number" ? (s as { lat: number }).lat : null,
    lon: typeof (s as { lon?: number }).lon === "number" ? (s as { lon: number }).lon : null,
  };
});

/** 店舗一覧の地域ボタン表示順（各店の `regionLabel` と一致） */
export const STORE_REGION_FILTER_ORDER: readonly string[] = [
  "北海道・東北",
  "関東",
  "中部",
  "近畿",
  "中国・四国",
  "九州・沖縄",
  "海外",
];

/** ボタン表記の上書き（未指定は `regionLabel` をそのまま表示） */
export const STORE_REGION_BUTTON_LABEL: Partial<Record<string, string>> = {
  近畿: "関西・近畿",
};

export const STORE_OPTIONS: StoreOption[] = STORES.map((s) => ({
  value: s.slug,
  label: s.label,
}));

export const DEFAULT_STORE = STORES[0].slug;

export function getStoreMetaBySlug(slug: string | null | undefined): StoreMeta {
  if (!slug) return STORES[0];
  const normalized = slug.toLowerCase();
  const found = STORES.find((s) => s.slug === normalized);
  if (!found && typeof window !== "undefined") {
    console.warn(`[getStoreMetaBySlug] unknown slug "${slug}", falling back to default store`);
  }
  return found ?? STORES[0];
}

/** 一致する店舗が無いときは null（cron 等でデフォルト店にフォールバックしない） */
export function getStoreMetaBySlugStrict(slug: string | null | undefined): StoreMeta | null {
  if (!slug?.trim()) return null;
  const normalized = slug.trim().toLowerCase();
  return STORES.find((s) => s.slug === normalized) ?? null;
}

export function getStoreMetaById(storeId: string | null | undefined): StoreMeta {
  if (!storeId) return STORES[0];
  return STORES.find((s) => s.storeId === storeId) ?? STORES[0];
}
