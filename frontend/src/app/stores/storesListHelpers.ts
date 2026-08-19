import { jstHm } from "@/lib/date/jst";
import { crowdTierFromPeakTotal } from "@/lib/store/crowdThresholds";

export type BrandFilter = "all" | "oriental" | "jis" | "aisekiya";
/**
 * 一覧ページが /api/forecast_today(_multi) から読む「合計だけの予測行」。
 * lib/forecast/types.ts の `ForecastPoint`（men_pred/women_pred 込み・ts 任意）とは
 * 別物なので、同名にして「予測点の型は揃っている」と誤読されないよう名前を分けている。
 */
export type ForecastTotalRow = { ts: string; total_pred?: number };

export const BRAND_TABS: { id: BrandFilter; label: string }[] = [
  { id: "all", label: "すべて" },
  { id: "oriental", label: "ORIENTAL LOUNGE" },
  { id: "jis", label: "JIS" },
  { id: "aisekiya", label: "相席屋" },
];

export const STORES_PER_PAGE = 12;

/** JST の「HH:MM」。実体は lib/date/jst の jstHm（Intl オプションの手書きコピーを増やさない）。 */
export const toHmJst = (iso: string): string => jstHm(new Date(iso));

// 閾値の数値は lib/store/crowdThresholds.ts（LINE 下書きの crowd_label と共有）。
// 文言はこの一覧固有（LINE 側は 混み/ほどよい/空き）。
export const crowdLabelFromPred = (maxPred: number): string => {
  const tier = crowdTierFromPeakTotal(maxPred);
  return tier === "busy" ? "混雑" : tier === "moderate" ? "ほどよい" : "空いている";
};
