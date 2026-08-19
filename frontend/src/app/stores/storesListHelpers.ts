import { crowdTierFromPeakTotal } from "@/lib/store/crowdThresholds";

export type BrandFilter = "all" | "oriental" | "jis" | "aisekiya";
export type ForecastPoint = { ts: string; total_pred?: number };

export const BRAND_TABS: { id: BrandFilter; label: string }[] = [
  { id: "all", label: "すべて" },
  { id: "oriental", label: "ORIENTAL LOUNGE" },
  { id: "jis", label: "JIS" },
  { id: "aisekiya", label: "相席屋" },
];

export const STORES_PER_PAGE = 12;

export const toHmJst = (iso: string): string =>
  new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));

// 閾値の数値は lib/store/crowdThresholds.ts（LINE 下書きの crowd_label と共有）。
// 文言はこの一覧固有（LINE 側は 混み/ほどよい/空き）。
export const crowdLabelFromPred = (maxPred: number): string => {
  const tier = crowdTierFromPeakTotal(maxPred);
  return tier === "busy" ? "混雑" : tier === "moderate" ? "ほどよい" : "空いている";
};
