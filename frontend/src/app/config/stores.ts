import rawStores from "@/data/stores.json";

export type StoreOption = { value: string; label: string };

export type StoreMeta = {
  slug: string;
  storeId: string;
  label: string;
  areaLabel: string;
  regionLabel: string;
  mapsQueryBase: string;
  brand: "oriental";
};

// Source of truth: frontend/src/data/stores.json (shared with Python backend)
export const STORES: StoreMeta[] = rawStores.map((s) => ({
  slug: s.slug,
  storeId: s.store_id,
  label: s.label,
  areaLabel: s.area_label,
  regionLabel: s.region_label,
  mapsQueryBase: s.maps_query_base,
  brand: "oriental" as const,
}));

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
