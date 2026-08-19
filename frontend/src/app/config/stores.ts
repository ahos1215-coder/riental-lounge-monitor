import rawStores from "@/data/stores.json";

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

/**
 * 男女の合計人数から「店舗全体の席の埋まり具合(%)」を復元する。
 *
 * `capacity` は**片性別あたり**の席数なので、店舗全体の座席数は `capacity * 2`。
 * この `×2` は店舗ページ／エリア／カード／比較／マイページ／週報の 11 箇所に手書きされており、
 * 付け忘れると%が倍に出る（実際に間違えやすい）ため関数名に昇格させた。
 * 片性別の%が欲しい場合は従来どおり seatFullnessPercent(count, capacity) を使う。
 */
export function seatFullnessPercentOfTotal(
  total: number,
  capacity: number | null | undefined,
): number | null {
  if (!capacity || capacity <= 0) return null;
  return seatFullnessPercent(total, capacity * 2);
}

/** ブランドの表示ラベル (StoreCard 等で使用) */
export const BRAND_DISPLAY_LABEL: Record<BrandId, string> = {
  oriental: "ORIENTAL LOUNGE",
  aisekiya: "相席屋",
  jis: "JIS",
};

/**
 * ブランドの短縮表示名（日本語）。buildStoreFullName / buildStoreTitleName / JSON-LDの brand
 * 全てがここを単一ソースにする。BRAND_DISPLAY_LABEL とは別物（そちらは "ORIENTAL LOUNGE" という
 * 英語表記で StoreCard 等の別UIが使っており、ここを変えると影響範囲が広いため触らない）。
 */
const BRAND_SHORT_NAME: Record<BrandId, string> = {
  oriental: "オリエンタルラウンジ",
  aisekiya: "相席屋",
  jis: "JIS",
};

/** 店舗名表示のフルネーム生成 (例: "オリエンタルラウンジ 渋谷本店") */
export function buildStoreFullName(meta: StoreMeta): string {
  const prefix = BRAND_SHORT_NAME[meta.brand];
  return prefix ? `${prefix} ${meta.label}` : meta.label;
}

/**
 * <title>タグ専用の短縮表記（ブランド名+店舗名をスペース無しで連結。例: "オリエンタルラウンジ小倉"）。
 * buildStoreFullName（スペースあり、本文・JSON-LD向け）より1文字節約するための別ヘルパー。
 * 日本語タイトルはモバイルSERPで実質30〜35字で切れるため、店舗ページのタイトルはこちらを使う。
 */
export function buildStoreTitleName(meta: StoreMeta): string {
  return `${BRAND_SHORT_NAME[meta.brand]}${meta.label}`;
}

/**
 * ブランド名単体（例: "オリエンタルラウンジ" / "相席屋"）。JSON-LD の brand フィールド用。
 * 必ず引数の meta と同じブランドの文字列を返すため、呼び出し側でブランドを混同する余地がない。
 */
export function buildStoreBrandName(meta: StoreMeta): string {
  return BRAND_SHORT_NAME[meta.brand];
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

export const DEFAULT_STORE = STORES[0].slug;

/**
 * slug → 店舗メタ。**見つからなければ既定店（STORES[0]）を黙って返す**（lookup-or-default）。
 * 旧名 `getStoreMetaBySlug` は「引く」だけに見えて実際は縮退するため、2026-08-19 に改名した。
 *
 * 注意: localStorage 由来の slug（マイページの履歴/お気に入り）には閉店店舗（例: 2026-07-11 閉店の
 * sapporo_ag）が残り得る。その場合カードは既定店の名前・数値で描画され、リンク先だけ 404 になる。
 * 「未知の slug は表示しない」に変える案は表示が変わるためオーナー判断待ちの別チケット。
 * 未知を弾きたい呼び出しは getStoreMetaBySlugStrict（null 返し）を使う。
 */
export function getStoreMetaBySlugOrDefault(slug: string | null | undefined): StoreMeta {
  if (!slug) return STORES[0];
  const normalized = slug.toLowerCase();
  const found = STORES.find((s) => s.slug === normalized);
  if (!found && typeof window !== "undefined") {
    console.warn(`[getStoreMetaBySlugOrDefault] unknown slug "${slug}", falling back to default store`);
  }
  return found ?? STORES[0];
}

/** 一致する店舗が無いときは null（cron 等でデフォルト店にフォールバックしない） */
export function getStoreMetaBySlugStrict(slug: string | null | undefined): StoreMeta | null {
  if (!slug?.trim()) return null;
  const normalized = slug.trim().toLowerCase();
  return STORES.find((s) => s.slug === normalized) ?? null;
}
