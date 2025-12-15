import { getStoreMetaBySlug } from "./stores";

export type SecondVenuePurpose =
  | "darts"
  | "karaoke"
  | "ramen"
  | "love_hotel";

// フロントエンドでの検索リンクのみを提供（バックエンドは未使用）
export type VenueServiceStyle = "unknown" | "hostess" | "non_hostess";

export type SecondVenueMapLink = {
  id: string;
  purpose: SecondVenuePurpose;
  label: string;
  description: string;
  url: string;
  serviceStyleHint: VenueServiceStyle;
};

type PurposeConfig = {
  purpose: SecondVenuePurpose;
  label: string;
  description: string;
  keyword: string;
};

const PURPOSE_CONFIGS: PurposeConfig[] = [
  {
    purpose: "darts",
    label: "ダーツで二次会",
    description: "近くのダーツバーを Google マップで開きます。",
    keyword: "ダーツバー",
  },
  {
    purpose: "karaoke",
    label: "カラオケで二次会",
    description: "近くのカラオケ店を Google マップで開きます。",
    keyword: "カラオケ",
  },
  {
    purpose: "ramen",
    label: "締めのラーメン",
    description: "近くのラーメン屋を Google マップで開きます。",
    keyword: "ラーメン",
  },
  {
    purpose: "love_hotel",
    label: "ゆっくりできる場所を探す",
    description: "近くのラブホテルを Google マップで開きます。",
    keyword: "ラブホテル",
  },
];

function buildMapSearchUrl(areaLabel: string, keyword: string): string {
  const query = `${areaLabel} ${keyword}`.trim();
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

export function getSecondVenueMapLinks(storeSlug: string): SecondVenueMapLink[] {
  const meta = getStoreMetaBySlug(storeSlug);
  const areaLabel = meta.mapsQueryBase || meta.areaLabel || meta.label;

  return PURPOSE_CONFIGS.map((config) => ({
    id: `${meta.slug}-${config.purpose}`,
    purpose: config.purpose,
    label: config.label,
    description: config.description,
    url: buildMapSearchUrl(areaLabel, config.keyword),
    serviceStyleHint: "unknown",
  }));
}
