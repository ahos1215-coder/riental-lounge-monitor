import { isPercentCrowdBrand, seatFullnessPercentOfTotal, type BrandId } from "@/app/config/stores";

export type CrowdBaselineDisplay = {
  /** 表示する数値（不明時は "-"） */
  value: string;
  /** 数値の後ろに出す単位（" 人" / "%"） */
  unit: string;
  /** metric_interpretations.baseline_label が無いときの説明文 */
  fallbackHint: string;
};

/**
 * 週報の「混み具合の基準」(baseline_p95_total) の表示値。
 *
 * 相席屋は在店人数を公開しておらず、当プロジェクトが持つ人数は %から逆算した推定値なので
 * 人数を出してはいけない（CLAUDE.md §4-3）。店舗ページ／比較ページ／マイページと同じく
 * `seatFullnessPercentOfTotal(合計人数, capacity)` で「席の埋まり具合(%)」に戻して表示する
 * （capacity は片性別あたりの席数なので ×2 が店舗全体の座席数。新しい式は作らない）。
 */
export function buildCrowdBaselineDisplay(
  store: { brand: BrandId; capacity: number | null },
  baselineP95Total: unknown,
): CrowdBaselineDisplay {
  const percentMode = isPercentCrowdBrand(store.brand) && !!store.capacity;
  const unit = percentMode ? "%" : " 人";
  const fallbackHint = percentMode
    ? "この埋まり具合以上なら「混んでいる」目安"
    : "この人数以上なら「混んでいる」目安";

  if (typeof baselineP95Total !== "number" || Number.isNaN(baselineP95Total)) {
    return { value: "-", unit, fallbackHint };
  }

  if (percentMode) {
    const pct = seatFullnessPercentOfTotal(Math.round(baselineP95Total), store.capacity);
    return { value: pct == null ? "-" : String(pct), unit, fallbackHint };
  }

  return { value: baselineP95Total.toFixed(0), unit, fallbackHint };
}
