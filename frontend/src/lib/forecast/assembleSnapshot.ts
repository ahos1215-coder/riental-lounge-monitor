// frontend/src/lib/forecast/assembleSnapshot.ts
//
// StoreSnapshot（店舗ページの「今・ピーク・系列」の表示単位）を組み立てる純粋関数。
//
// 経緯: 同じ組み立てが 4 箇所に手書きされていた。
//   ① useStorePreviewData の実測のみスナップショット
//   ② useStorePreviewData の applyMergedForecast（予測合流）
//   ③ store/[id]/page.tsx の完了夜（forecast_snapshot オーバーレイ）分岐
//   ④ store/[id]/page.tsx の進行中の夜（forecast_today）分岐
// SSR（生HTML/SEO本文）と CSR（グラフ）は「同じ数字が出ること」が前提なのに、
// ピークの取り方や latestActualTs のフォールバック順が人手同期に頼っていた。
//
// 設計上の約束（重要）:
// - この関数は **一切の条件分岐・既定値を持たない**。level / recommendation /
//   forecastUpdatedLabel / forecastStatus / hasData / latestActualTs / completedNight は
//   呼び出し側が現行どおりの式で決めて渡す。
//   （hook と page.tsx では forecastStatus / forecastUpdatedLabel の決め方が元々違う。
//    それは既存の意図的な差分であり、ここで統一してはならない。
//    番犬: src/app/hooks/assembleStoreSnapshot.parity.test.ts）
import { pickCurrentActual, pickPeak } from "./seriesAnalysis";
import type { StoreSnapshot, TimeSeriesPoint } from "./types";

/** pickLatestActualPoint（seriesAnalysis）の戻り値の形。 */
export type LatestActualPoint = {
  nowMen: number;
  nowWomen: number;
  ts: string | null;
};

/**
 * 「◯分前更新」に使う最新実測の ts。
 * 夜窓フィルタ前の全データ（latestActual）を優先し、無ければ系列の最後の実測点で代替する。
 */
export function resolveLatestActualTs(
  latestActual: LatestActualPoint | null,
  series: TimeSeriesPoint[],
): string | null {
  return (
    latestActual?.ts ??
    [...series].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
    null
  );
}

export type AssembleStoreSnapshotInput = {
  /** 展開元。①③④は buildBaseSnapshot(meta)、②は実測スナップショット（引き継ぎたい値があるため）。 */
  base: StoreSnapshot;
  /** 実際に描画する系列（空フォールバック適用済み）。 */
  series: TimeSeriesPoint[];
  /** 夜窓フィルタ前の最新実測点（無ければ null）。now 値の優先ソース。 */
  latestActual: LatestActualPoint | null;
  /** ピークを実測点のみから取るか（完了夜のオーバーレイ表示では true）。 */
  actualOnlyPeak: boolean;
  level: string;
  recommendation: string;
  forecastUpdatedLabel: string;
  hasData: boolean;
  forecastStatus: StoreSnapshot["forecastStatus"];
  latestActualTs: string | null;
  completedNight: boolean;
};

/** 上記 4 経路が共有する「値の詰め方」だけを担う。判断は一切しない。 */
export function assembleStoreSnapshot(input: AssembleStoreSnapshotInput): StoreSnapshot {
  const {
    base,
    series,
    latestActual,
    actualOnlyPeak,
    level,
    recommendation,
    forecastUpdatedLabel,
    hasData,
    forecastStatus,
    latestActualTs,
    completedNight,
  } = input;

  const current = pickCurrentActual(series);
  const nowMen = latestActual?.nowMen ?? current.nowMen;
  const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
  const peak = pickPeak(series, { actualOnly: actualOnlyPeak });

  return {
    ...base,
    level,
    recommendation,
    nowMen: Math.round(nowMen),
    nowWomen: Math.round(nowWomen),
    nowTotal: Math.round(nowMen + nowWomen),
    peakTotal: Math.round(peak.peakTotal),
    peakTimeLabel: peak.peakTimeLabel,
    peakTs: peak.peakTs,
    peakMen: peak.peakMen,
    peakWomen: peak.peakWomen,
    forecastUpdatedLabel,
    series,
    hasData,
    forecastStatus,
    latestActualTs,
    completedNight,
  };
}
