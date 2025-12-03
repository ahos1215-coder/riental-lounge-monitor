import { getSlugFromStoreId, type StoreId } from "../../components/MeguribiDashboardPreview";
import { STORE_OPTIONS } from "./stores";

export type SecondVenuePurpose =
  | "darts"
  | "karaoke"
  | "ramen"
  | "love_hotel";

// 将来 NLP で「接客メインか」を判定するためのヒント枠 (現状は unknown 固定)
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
    description: "近くのダーツバーを Googleマップで開きます。",
    keyword: "ダーツバー",
  },
  {
    purpose: "karaoke",
    label: "カラオケで二次会",
    description: "近くのカラオケ店を Googleマップで開きます。",
    keyword: "カラオケ",
  },
  {
    purpose: "ramen",
    label: "締めのラーメン",
    description: "近くのラーメン屋を Googleマップで開きます。",
    keyword: "ラーメン",
  },
  {
    purpose: "love_hotel",
    label: "ゆっくりできる場所を探す",
    description: "近くのラブホテルを Googleマップで開きます。",
    keyword: "ラブホテル",
  },
];

function getAreaLabelFromSlug(slug: string): string {
  const match = STORE_OPTIONS.find((opt) => opt.value === slug);
  const label = match?.label?.trim();
  return label && label.length > 0 ? label : slug;
}

function buildMapSearchUrl(areaLabel: string, keyword: string): string {
  const query = `${areaLabel} ${keyword}`.trim();
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

export function getSecondVenueMapLinks(storeId: StoreId): SecondVenueMapLink[] {
  const slug = getSlugFromStoreId(storeId);
  const areaLabel = getAreaLabelFromSlug(slug);

  return PURPOSE_CONFIGS.map((config) => ({
    id: `${slug}-${config.purpose}`,
    purpose: config.purpose,
    label: config.label,
    description: config.description,
    url: buildMapSearchUrl(areaLabel, config.keyword),
    serviceStyleHint: "unknown",
  }));
}
