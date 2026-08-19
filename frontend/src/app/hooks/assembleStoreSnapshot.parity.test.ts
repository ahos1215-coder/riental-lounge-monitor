// frontend/src/app/hooks/assembleStoreSnapshot.parity.test.ts
//
// 番犬（C-02 / D-02）: StoreSnapshot の組み立ては 2026-08 まで 4 箇所に手書きされていた。
//   ① useStorePreviewData の実測のみ組み立て
//   ② useStorePreviewData の applyMergedForecast（予測合流）
//   ③ store/[id]/page.tsx の完了夜（forecast_snapshot オーバーレイ）分岐
//   ④ store/[id]/page.tsx の進行中の夜（forecast_today）分岐
// これを 1 つの純粋関数 assembleStoreSnapshot に集約した。
//
// このテストは「旧 4 実装をそのまま写経したレガシー版」と「新関数を使う現行呼び出し側と
// 同じ組み立て」の出力が deepEqual であること、かつ両者が固定の期待値と一致することを固定する。
// レガシー版は意図的に残す（新関数を誰かが"整えて"しまったら、ここが赤くなる）。
//
// 重要（意図的な既存差分・統一しないこと）:
//   forecastStatus / forecastUpdatedLabel の決め方は hook と page.tsx で元々違う。
//   - hook の合流後: 無条件 "ok" / formatNowHmJst(new Date())
//   - page.tsx 完了夜: snapshotPoints.length > 0 ? "ok" : "idle" / "更新済み" or "--:--"
//   新関数はこの 2 値を引数で受け取るだけで、内部で既定値も条件分岐も持たない。
import { describe, expect, it } from "vitest";
import { STORES } from "../config/stores";
import {
  buildBaseSnapshot,
  buildSeries,
  hasSeriesData,
  pickCurrentActual,
  pickLatestActualPoint,
  pickPeak,
  type ForecastPoint,
  type ForecastStatus,
  type RangePoint,
  type StoreSnapshot,
} from "./storePreviewSnapshot";
import {
  assembleStoreSnapshot,
  resolveLatestActualTs,
} from "@/lib/forecast/assembleSnapshot";

const META = STORES[0];
const baseOf = () => buildBaseSnapshot(META);

// ---------------------------------------------------------------------------
// レガシー実装（2026-08 時点の 4 箇所を写経。1 文字も"整えない"こと）
// ---------------------------------------------------------------------------

/** ① useStorePreviewData.ts:282-325（実測のみのスナップショット） */
function legacyHookActualOnly(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  initialForecastStatus: ForecastStatus,
  completedNight: boolean,
): StoreSnapshot {
  const baseSnapshot = baseOf();
  const actualOnlySeries = buildSeries(rangePoints, []);
  const effectiveActualSeries =
    actualOnlySeries.length > 0 ? actualOnlySeries : baseSnapshot.series;
  const latestActual = pickLatestActualPoint(allRangePoints);
  const hasData = hasSeriesData(actualOnlySeries) || latestActual !== null;

  const current = pickCurrentActual(effectiveActualSeries);
  const nowMen = latestActual?.nowMen ?? current.nowMen;
  const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
  const {
    peakTotal,
    peakTimeLabel,
    peakTs: peakTsVal,
    peakMen: peakMenVal,
    peakWomen: peakWomenVal,
  } = pickPeak(effectiveActualSeries);
  const latestActualTs =
    latestActual?.ts ??
    [...effectiveActualSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)
      ?.ts ??
    null;

  return {
    ...baseSnapshot,
    level: hasData ? "データ取得済み" : "データなし",
    recommendation: hasData ? "データ取得済み" : "データなし",
    nowMen: Math.round(nowMen),
    nowWomen: Math.round(nowWomen),
    nowTotal: Math.round(nowMen + nowWomen),
    peakTotal: Math.round(peakTotal),
    peakTimeLabel,
    peakTs: peakTsVal,
    peakMen: peakMenVal,
    peakWomen: peakWomenVal,
    forecastUpdatedLabel: "--:--",
    series: effectiveActualSeries,
    hasData,
    forecastStatus: initialForecastStatus,
    latestActualTs,
    completedNight,
  };
}

/** ② useStorePreviewData.ts:345-374（applyMergedForecast の合流スナップショット） */
function legacyHookMerged(
  baseSnapshotResolved: StoreSnapshot,
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  forecastPoints: ForecastPoint[],
  overlayAllForecast: boolean,
  completedNight: boolean,
  forecastUpdatedLabel: string,
): StoreSnapshot {
  const latestActual = pickLatestActualPoint(allRangePoints);
  const mergedSeries = buildSeries(rangePoints, forecastPoints, overlayAllForecast);
  const effectiveMergedSeries =
    mergedSeries.length > 0 ? mergedSeries : baseSnapshotResolved.series;
  const mergedCurrent = pickCurrentActual(effectiveMergedSeries);
  const mergedNowMen = latestActual?.nowMen ?? mergedCurrent.nowMen;
  const mergedNowWomen = latestActual?.nowWomen ?? mergedCurrent.nowWomen;
  const mergedPeak = pickPeak(effectiveMergedSeries, { actualOnly: completedNight });
  return {
    ...baseSnapshotResolved,
    nowMen: Math.round(mergedNowMen),
    nowWomen: Math.round(mergedNowWomen),
    nowTotal: Math.round(mergedNowMen + mergedNowWomen),
    peakTotal: Math.round(mergedPeak.peakTotal),
    peakTimeLabel: mergedPeak.peakTimeLabel,
    peakTs: mergedPeak.peakTs,
    peakMen: mergedPeak.peakMen,
    peakWomen: mergedPeak.peakWomen,
    forecastUpdatedLabel,
    series: effectiveMergedSeries,
    hasData: hasSeriesData(mergedSeries) || baseSnapshotResolved.hasData,
    forecastStatus: "ok",
  };
}

/** ③ store/[id]/page.tsx:177-228（完了夜分岐）。hasData=false のとき null を返すのも旧仕様。 */
function legacyPageCompletedNight(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  snapshotPoints: ForecastPoint[],
): StoreSnapshot | null {
  const baseSnapshot = baseOf();
  const latestActual = pickLatestActualPoint(allRangePoints);

  const series = buildSeries(rangePoints, snapshotPoints, true);
  const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
  const hasData = hasSeriesData(series) || latestActual !== null;
  if (!hasData) return null;

  const current = pickCurrentActual(effectiveSeries);
  const nowMen = latestActual?.nowMen ?? current.nowMen;
  const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
  const { peakTotal, peakTimeLabel, peakTs, peakMen, peakWomen } = pickPeak(effectiveSeries, {
    actualOnly: true,
  });
  const latestActualTs =
    latestActual?.ts ??
    [...effectiveSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
    null;

  return {
    ...baseSnapshot,
    level: "データ取得済み",
    recommendation: "データ取得済み",
    nowMen: Math.round(nowMen),
    nowWomen: Math.round(nowWomen),
    nowTotal: Math.round(nowMen + nowWomen),
    peakTotal: Math.round(peakTotal),
    peakTimeLabel,
    peakTs,
    peakMen,
    peakWomen,
    forecastUpdatedLabel: snapshotPoints.length > 0 ? "更新済み" : "--:--",
    series: effectiveSeries,
    hasData,
    forecastStatus: snapshotPoints.length > 0 ? "ok" : "idle",
    latestActualTs,
    completedNight: true,
  };
}

/** ④ store/[id]/page.tsx:231-283（進行中の夜の分岐） */
function legacyPageOngoing(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  allForecastPoints: ForecastPoint[],
  forecastPoints: ForecastPoint[],
  isInsufficientHistory: boolean,
): StoreSnapshot | null {
  const baseSnapshot = baseOf();
  const latestActual = pickLatestActualPoint(allRangePoints);

  const series = buildSeries(rangePoints, forecastPoints);
  const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
  const hasData = hasSeriesData(series) || latestActual !== null;
  if (!hasData) return null;

  const current = pickCurrentActual(effectiveSeries);
  const nowMen = latestActual?.nowMen ?? current.nowMen;
  const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
  const { peakTotal, peakTimeLabel, peakTs, peakMen, peakWomen } = pickPeak(effectiveSeries);
  const latestActualTs =
    latestActual?.ts ??
    [...effectiveSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
    null;

  const forecastStatus: StoreSnapshot["forecastStatus"] = isInsufficientHistory
    ? "insufficient_history"
    : allForecastPoints.length > 0
      ? "ok"
      : "idle";

  return {
    ...baseSnapshot,
    level: "データ取得済み",
    recommendation: "データ取得済み",
    nowMen: Math.round(nowMen),
    nowWomen: Math.round(nowWomen),
    nowTotal: Math.round(nowMen + nowWomen),
    peakTotal: Math.round(peakTotal),
    peakTimeLabel,
    peakTs,
    peakMen,
    peakWomen,
    forecastUpdatedLabel: allForecastPoints.length > 0 ? "更新済み" : "--:--",
    series: effectiveSeries,
    hasData,
    forecastStatus,
    latestActualTs,
    completedNight: false,
  };
}

// ---------------------------------------------------------------------------
// 新実装（現行の呼び出し側と同じ組み立て。production 側と同じ順序・同じ引数で書く）
// ---------------------------------------------------------------------------

function newHookActualOnly(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  initialForecastStatus: ForecastStatus,
  completedNight: boolean,
): StoreSnapshot {
  const baseSnapshot = baseOf();
  const actualOnlySeries = buildSeries(rangePoints, []);
  const effectiveActualSeries =
    actualOnlySeries.length > 0 ? actualOnlySeries : baseSnapshot.series;
  const latestActual = pickLatestActualPoint(allRangePoints);
  const hasData = hasSeriesData(actualOnlySeries) || latestActual !== null;

  return assembleStoreSnapshot({
    base: baseSnapshot,
    series: effectiveActualSeries,
    latestActual,
    actualOnlyPeak: false,
    level: hasData ? "データ取得済み" : "データなし",
    recommendation: hasData ? "データ取得済み" : "データなし",
    forecastUpdatedLabel: "--:--",
    hasData,
    forecastStatus: initialForecastStatus,
    latestActualTs: resolveLatestActualTs(latestActual, effectiveActualSeries),
    completedNight,
  });
}

function newHookMerged(
  baseSnapshotResolved: StoreSnapshot,
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  forecastPoints: ForecastPoint[],
  overlayAllForecast: boolean,
  completedNight: boolean,
  forecastUpdatedLabel: string,
): StoreSnapshot {
  const latestActual = pickLatestActualPoint(allRangePoints);
  const mergedSeries = buildSeries(rangePoints, forecastPoints, overlayAllForecast);
  const effectiveMergedSeries =
    mergedSeries.length > 0 ? mergedSeries : baseSnapshotResolved.series;

  return assembleStoreSnapshot({
    base: baseSnapshotResolved,
    series: effectiveMergedSeries,
    latestActual,
    actualOnlyPeak: completedNight,
    level: baseSnapshotResolved.level,
    recommendation: baseSnapshotResolved.recommendation,
    forecastUpdatedLabel,
    hasData: hasSeriesData(mergedSeries) || baseSnapshotResolved.hasData,
    forecastStatus: "ok",
    latestActualTs: baseSnapshotResolved.latestActualTs,
    completedNight: baseSnapshotResolved.completedNight,
  });
}

function newPageCompletedNight(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  snapshotPoints: ForecastPoint[],
): StoreSnapshot | null {
  const baseSnapshot = baseOf();
  const latestActual = pickLatestActualPoint(allRangePoints);
  const series = buildSeries(rangePoints, snapshotPoints, true);
  const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
  const hasData = hasSeriesData(series) || latestActual !== null;
  if (!hasData) return null;

  return assembleStoreSnapshot({
    base: baseSnapshot,
    series: effectiveSeries,
    latestActual,
    actualOnlyPeak: true,
    level: "データ取得済み",
    recommendation: "データ取得済み",
    forecastUpdatedLabel: snapshotPoints.length > 0 ? "更新済み" : "--:--",
    hasData,
    forecastStatus: snapshotPoints.length > 0 ? "ok" : "idle",
    latestActualTs: resolveLatestActualTs(latestActual, effectiveSeries),
    completedNight: true,
  });
}

function newPageOngoing(
  allRangePoints: RangePoint[],
  rangePoints: RangePoint[],
  allForecastPoints: ForecastPoint[],
  forecastPoints: ForecastPoint[],
  isInsufficientHistory: boolean,
): StoreSnapshot | null {
  const baseSnapshot = baseOf();
  const latestActual = pickLatestActualPoint(allRangePoints);
  const series = buildSeries(rangePoints, forecastPoints);
  const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
  const hasData = hasSeriesData(series) || latestActual !== null;
  if (!hasData) return null;

  return assembleStoreSnapshot({
    base: baseSnapshot,
    series: effectiveSeries,
    latestActual,
    actualOnlyPeak: false,
    level: "データ取得済み",
    recommendation: "データ取得済み",
    forecastUpdatedLabel: allForecastPoints.length > 0 ? "更新済み" : "--:--",
    hasData,
    forecastStatus: isInsufficientHistory
      ? "insufficient_history"
      : allForecastPoints.length > 0
        ? "ok"
        : "idle",
    latestActualTs: resolveLatestActualTs(latestActual, effectiveSeries),
    completedNight: false,
  });
}

// ---------------------------------------------------------------------------
// フィクスチャ（本番形: 実測は UTC マイクロ秒 ts、予測は JST 15分グリッド ts）
// ---------------------------------------------------------------------------

/** 2026-08-18 の夜（19:00 JST〜翌05:00 JST）の実測 3 点 */
const ACTUALS: RangePoint[] = [
  { ts: "2026-08-18T10:30:12.123456Z", men: 12, women: 8, total: 20 }, // 19:30 JST
  { ts: "2026-08-18T12:00:41.987654Z", men: 30, women: 22, total: 52 }, // 21:00 JST
  { ts: "2026-08-18T13:45:03.000001Z", men: 25, women: 19, total: 44 }, // 22:45 JST
];

/** 実測より未来を含む予測（21:00 は実測と重なる・23:00/00:00 は未来） */
const FORECASTS: ForecastPoint[] = [
  { ts: "2026-08-18T21:00:00+09:00", men_pred: 28, women_pred: 20, total_pred: 48 },
  { ts: "2026-08-18T23:00:00+09:00", men_pred: 40, women_pred: 30, total_pred: 70 },
  { ts: "2026-08-19T00:00:00+09:00", men_pred: 35, women_pred: 28, total_pred: 63 },
];

/** 履歴不足店（バックエンドが null 行を返す） */
const FORECASTS_NULL: ForecastPoint[] = [
  { ts: "2026-08-18T23:00:00+09:00", men_pred: null, women_pred: null, total_pred: null },
];

describe("assembleStoreSnapshot — 旧4実装との等価性（番犬）", () => {
  it("① 進行中の夜・実測のみ（hook の実測スナップショット）", () => {
    const legacy = legacyHookActualOnly(ACTUALS, ACTUALS, "idle", false);
    const next = newHookActualOnly(ACTUALS, ACTUALS, "idle", false);
    expect(next).toEqual(legacy);
    // 値そのものも固定する（暗黙の既定値へ丸められていないことの検出）
    expect(next.nowMen).toBe(25);
    expect(next.nowWomen).toBe(19);
    expect(next.nowTotal).toBe(44);
    expect(next.peakTotal).toBe(52);
    expect(next.peakTimeLabel).toBe("21:00");
    expect(next.peakTs).toBe("2026-08-18T12:00:41.987654Z");
    expect(next.latestActualTs).toBe("2026-08-18T13:45:03.000001Z");
    expect(next.forecastUpdatedLabel).toBe("--:--");
    expect(next.forecastStatus).toBe("idle");
    expect(next.level).toBe("データ取得済み");
    expect(next.hasData).toBe(true);
    expect(next.completedNight).toBe(false);
  });

  it("② 進行中の夜・実測+予測合流（hook の applyMergedForecast / overlay なし）", () => {
    const seedLegacy = legacyHookActualOnly(ACTUALS, ACTUALS, "idle", false);
    const seedNext = newHookActualOnly(ACTUALS, ACTUALS, "idle", false);
    const label = "23:45"; // formatNowHmJst(new Date()) 相当を固定
    const legacy = legacyHookMerged(seedLegacy, ACTUALS, ACTUALS, FORECASTS, false, false, label);
    const next = newHookMerged(seedNext, ACTUALS, ACTUALS, FORECASTS, false, false, label);
    expect(next).toEqual(legacy);
    // 進行中は予測ピーク（23:00 の 70）を採用する
    expect(next.peakTotal).toBe(70);
    expect(next.peakTimeLabel).toBe("23:00");
    expect(next.forecastStatus).toBe("ok");
    expect(next.forecastUpdatedLabel).toBe(label);
    // latestActualTs は実測スナップショットから引き継ぐ（合流で再計算しない）
    expect(next.latestActualTs).toBe(seedNext.latestActualTs);
  });

  it("③ 完了夜・スナップショット予測を夜全体に重ねる（hook / overlay あり・ピークは実測のみ）", () => {
    const seedLegacy = legacyHookActualOnly(ACTUALS, ACTUALS, "idle", true);
    const seedNext = newHookActualOnly(ACTUALS, ACTUALS, "idle", true);
    const label = "05:10";
    const legacy = legacyHookMerged(seedLegacy, ACTUALS, ACTUALS, FORECASTS, true, true, label);
    const next = newHookMerged(seedNext, ACTUALS, ACTUALS, FORECASTS, true, true, label);
    expect(next).toEqual(legacy);
    // 予測 70 に上書きされず、実測ピーク 52 のまま
    expect(next.peakTotal).toBe(52);
    expect(next.peakTimeLabel).toBe("21:00");
    expect(next.completedNight).toBe(true);
  });

  it("④ 完了夜・page.tsx（snapshot あり）", () => {
    const legacy = legacyPageCompletedNight(ACTUALS, ACTUALS, FORECASTS);
    const next = newPageCompletedNight(ACTUALS, ACTUALS, FORECASTS);
    expect(next).toEqual(legacy);
    expect(next?.forecastUpdatedLabel).toBe("更新済み");
    expect(next?.forecastStatus).toBe("ok");
    expect(next?.peakTotal).toBe(52);
    expect(next?.completedNight).toBe(true);
  });

  it("⑤ 完了夜・page.tsx（snapshot なし＝空配列: idle と --:-- のまま）", () => {
    const legacy = legacyPageCompletedNight(ACTUALS, ACTUALS, []);
    const next = newPageCompletedNight(ACTUALS, ACTUALS, []);
    expect(next).toEqual(legacy);
    expect(next?.forecastUpdatedLabel).toBe("--:--");
    expect(next?.forecastStatus).toBe("idle");
  });

  it("⑥ 進行中の夜・page.tsx（forecast_today あり）", () => {
    const legacy = legacyPageOngoing(ACTUALS, ACTUALS, FORECASTS, FORECASTS, false);
    const next = newPageOngoing(ACTUALS, ACTUALS, FORECASTS, FORECASTS, false);
    expect(next).toEqual(legacy);
    expect(next?.forecastUpdatedLabel).toBe("更新済み");
    expect(next?.forecastStatus).toBe("ok");
    expect(next?.peakTotal).toBe(70);
  });

  it("⑦ 進行中の夜・page.tsx（insufficient_history: 予測は使わず状態だけ立てる）", () => {
    const legacy = legacyPageOngoing(ACTUALS, ACTUALS, [], [], true);
    const next = newPageOngoing(ACTUALS, ACTUALS, [], [], true);
    expect(next).toEqual(legacy);
    expect(next?.forecastStatus).toBe("insufficient_history");
    expect(next?.forecastUpdatedLabel).toBe("--:--");
    expect(next?.peakTotal).toBe(52);
  });

  it("⑧ 進行中の夜・page.tsx（予測が空: idle。null 予測行は使わない）", () => {
    const legacy = legacyPageOngoing(ACTUALS, ACTUALS, [], [], false);
    const next = newPageOngoing(ACTUALS, ACTUALS, [], [], false);
    expect(next).toEqual(legacy);
    expect(next?.forecastStatus).toBe("idle");
    // 全 null の予測行を渡しても系列には予測が乗らない
    const withNulls = newPageOngoing(ACTUALS, ACTUALS, FORECASTS_NULL, FORECASTS_NULL, false);
    expect(withNulls).toEqual(legacyPageOngoing(ACTUALS, ACTUALS, FORECASTS_NULL, FORECASTS_NULL, false));
  });

  it("⑨ データ無し（range 空）: hook は空スナップショット、page.tsx は null", () => {
    const legacy = legacyHookActualOnly([], [], "idle", false);
    const next = newHookActualOnly([], [], "idle", false);
    expect(next).toEqual(legacy);
    expect(next.hasData).toBe(false);
    expect(next.level).toBe("データなし");
    expect(next.nowTotal).toBe(0);
    expect(next.peakTimeLabel).toBe("--:--");
    expect(next.latestActualTs).toBeNull();
    expect(newPageCompletedNight([], [], [])).toBeNull();
    expect(legacyPageCompletedNight([], [], [])).toBeNull();
    expect(newPageOngoing([], [], [], [], false)).toBeNull();
    expect(legacyPageOngoing([], [], [], [], false)).toBeNull();
  });

  it("⑩ 夜窓フィルタで空になっても、窓外の最新実測があれば 0 固定にしない", () => {
    // rangePoints（窓内）は空、allRangePoints（窓外含む）だけ実測あり
    const legacy = legacyHookActualOnly(ACTUALS, [], "idle", false);
    const next = newHookActualOnly(ACTUALS, [], "idle", false);
    expect(next).toEqual(legacy);
    expect(next.hasData).toBe(true);
    expect(next.nowMen).toBe(25);
    expect(next.nowWomen).toBe(19);
    expect(next.latestActualTs).toBe("2026-08-18T13:45:03.000001Z");
    // 系列は空 → baseSnapshot の空系列にフォールバック
    expect(next.series).toEqual(baseOf().series);
  });

  it("⑪ hook 合流で系列が空なら実測スナップショットの系列を保つ", () => {
    const seedLegacy = legacyHookActualOnly(ACTUALS, [], "idle", false);
    const seedNext = newHookActualOnly(ACTUALS, [], "idle", false);
    const legacy = legacyHookMerged(seedLegacy, ACTUALS, [], [], false, false, "23:45");
    const next = newHookMerged(seedNext, ACTUALS, [], [], false, false, "23:45");
    expect(next).toEqual(legacy);
    expect(next.series).toEqual(seedNext.series);
  });

  it("resolveLatestActualTs: latestActual を優先し、無ければ系列の最後の実測点へ落ちる", () => {
    const series = buildSeries(ACTUALS, FORECASTS);
    expect(resolveLatestActualTs({ nowMen: 1, nowWomen: 2, ts: "X" }, series)).toBe("X");
    expect(resolveLatestActualTs({ nowMen: 1, nowWomen: 2, ts: null }, series)).toBe(
      "2026-08-18T13:45:03.000001Z",
    );
    expect(resolveLatestActualTs(null, series)).toBe("2026-08-18T13:45:03.000001Z");
    expect(resolveLatestActualTs(null, buildSeries([], FORECASTS))).toBeNull();
    expect(resolveLatestActualTs(null, [])).toBeNull();
  });
});
