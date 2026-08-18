import { STORES, type StoreMeta } from "./stores";

/**
 * エリア横断のランディングページ（/area/[area]）用の設定。
 * 「大阪 相席ラウンジ」等のビッグキーワード向けに、そのエリアに属する複数店舗を
 * まとめて紹介するハブページを作るための唯一の設定ソース。
 *
 * 店舗の表示名・エリアラベル等は stores.json（config/stores.ts の STORES）から都度引くだけで、
 * ここでは store slug の並びのみを保持する（表示名のハードコード禁止）。
 */
export type AreaId =
  | "osaka"
  | "nagoya"
  | "shibuya"
  | "ueno"
  | "yokohama"
  | "shizuoka"
  | "hamamatsu"
  | "machida"
  | "kokura"
  | "kobe"
  | "kumamoto"
  | "oita"
  | "takasaki"
  | "nagasaki";

export type AreaConfig = {
  /** URLセグメント (/area/{id}) 兼キー */
  id: AreaId;
  /** ページ文言で使うエリア表示名（例: "大阪"） */
  displayName: string;
  /** 検索意図の主キーワード（メタ文言の一貫性チェック用） */
  keyword: string;
  /** このエリアに属する店舗の slug 一覧（config/stores.ts の STORES.slug と一致させる） */
  storeSlugs: string[];
};

/**
 * 14エリア固定リスト。新しいエリアを追加する場合はここに1件足すだけで
 * /area/[area]/page.tsx の generateStaticParams・sitemap.ts に自動反映される。
 *
 * 前半5件（osaka〜yokohama）は複数店舗が集まる集約ハブ。後半9件（shizuoka〜nagasaki）は
 * GSC実測（2026-08時点・直近28日）で「相席ラウンジ/相席 + 地名」の一般語検索が付いているのに
 * 個別店舗ページが弱く、/stores（一覧）だけが拾って0クリックに終わっていた単独店舗エリア。
 * 該当地名は実在店舗が1件のみのため、そのエリアの店舗一覧セクションも1件になる
 * （空エリアの新設ではなく、既存の実在店舗にキーワード受け皿ページを1枚足すだけ）。
 * page.tsx 側は stores.length===1 のときに「複数店舗を比較」を前提にした文言を出さないよう
 * 単数/複数で分岐している。
 */
export const AREAS: AreaConfig[] = [
  {
    id: "osaka",
    displayName: "大阪",
    keyword: "大阪 相席ラウンジ",
    storeSlugs: ["osaka_ekimae", "umeda_ag", "tenma", "shinsaibashi", "namba"],
  },
  {
    id: "nagoya",
    displayName: "名古屋",
    keyword: "名古屋 相席ラウンジ",
    storeSlugs: ["nagoya_ag", "nagoya_nishiki", "nagoya_sakae"],
  },
  {
    id: "shibuya",
    displayName: "渋谷",
    keyword: "渋谷 相席ラウンジ",
    storeSlugs: ["shibuya", "shibuya_ag", "ay_shibuya"],
  },
  {
    id: "ueno",
    displayName: "上野",
    keyword: "上野 相席ラウンジ",
    storeSlugs: ["ueno", "ueno_ag", "ay_ueno"],
  },
  {
    id: "yokohama",
    displayName: "横浜",
    keyword: "横浜 相席ラウンジ",
    storeSlugs: ["yokohama", "ay_yokohama"],
  },
  {
    id: "shizuoka",
    displayName: "静岡",
    keyword: "静岡 相席ラウンジ",
    storeSlugs: ["shizuoka"],
  },
  {
    id: "hamamatsu",
    displayName: "浜松",
    keyword: "浜松 相席ラウンジ",
    storeSlugs: ["hamamatsu"],
  },
  {
    id: "machida",
    displayName: "町田",
    keyword: "町田 相席ラウンジ",
    storeSlugs: ["machida"],
  },
  {
    id: "kokura",
    displayName: "小倉",
    keyword: "小倉 相席ラウンジ",
    storeSlugs: ["kokura"],
  },
  {
    id: "kobe",
    displayName: "神戸",
    keyword: "神戸 相席ラウンジ",
    storeSlugs: ["kobe"],
  },
  {
    id: "kumamoto",
    displayName: "熊本",
    keyword: "熊本 相席ラウンジ",
    storeSlugs: ["kumamoto"],
  },
  {
    id: "oita",
    displayName: "大分",
    keyword: "大分 相席ラウンジ",
    storeSlugs: ["oita"],
  },
  {
    id: "takasaki",
    displayName: "高崎",
    keyword: "高崎 相席ラウンジ",
    storeSlugs: ["takasaki"],
  },
  // 長崎はGSC実測で「相席屋 長崎」の検索が付いている（相席屋の店舗はサイト対象外だが、
  // 相席ラウンジを探す人の受け皿としてオリエンタルラウンジ長崎のハブを用意する。
  // 発見最優先方針・2026-08-19）。
  {
    id: "nagasaki",
    displayName: "長崎",
    keyword: "長崎 相席ラウンジ",
    storeSlugs: ["nagasaki"],
  },
];

const AREA_BY_ID = new Map<AreaId, AreaConfig>(AREAS.map((a) => [a.id, a]));

/** slug → AreaId の逆引き（1店舗が複数エリアに属する場合は最初に見つかったものを返す） */
const AREA_ID_BY_STORE_SLUG = new Map<string, AreaId>();
for (const area of AREAS) {
  for (const slug of area.storeSlugs) {
    if (!AREA_ID_BY_STORE_SLUG.has(slug)) AREA_ID_BY_STORE_SLUG.set(slug, area.id);
  }
}

export function getAreaConfig(id: string | null | undefined): AreaConfig | null {
  if (!id) return null;
  return AREA_BY_ID.get(id as AreaId) ?? null;
}

/** 指定エリアに属する店舗の StoreMeta を storeSlugs の並び順で返す（存在しない slug は無視）。 */
export function getAreaStores(area: AreaConfig): StoreMeta[] {
  const bySlug = new Map(STORES.map((s) => [s.slug, s]));
  return area.storeSlugs
    .map((slug) => bySlug.get(slug))
    .filter((s): s is StoreMeta => Boolean(s));
}

/** 店舗 slug が属するエリア設定（無ければ null）。店舗ページからの「{エリア}一覧へ」導線に使う。 */
export function getAreaConfigForStoreSlug(slug: string | null | undefined): AreaConfig | null {
  if (!slug) return null;
  const areaId = AREA_ID_BY_STORE_SLUG.get(slug);
  if (!areaId) return null;
  return AREA_BY_ID.get(areaId) ?? null;
}
