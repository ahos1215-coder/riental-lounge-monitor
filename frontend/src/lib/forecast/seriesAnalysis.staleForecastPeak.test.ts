import { describe, it, expect } from "vitest";
import { buildSeries, pickPeak } from "@/lib/forecast/seriesAnalysis";
import type { RangePoint, ForecastPoint } from "@/app/hooks/storePreviewSnapshot";

/**
 * 「進行中の夜のピーク目安が、既に外れた過去時刻の予測値を拾う」バグの回帰テスト。
 *
 * 背景:
 *   buildSeries は overlayAllForecast=false（today 進行中）のとき「最後の実測より過去の
 *   予測は点線として描かない（＝null にする）」つもりだったが、その null 化は
 *   `map.get(p.ts)` で**同一 ts の実測が既に存在する場合だけ**適用されていた。
 *
 *   ところが本番の ts は
 *     - 実測  (/api/range)         : "2026-08-18T19:55:22.571678+00:00"（秒・マイクロ秒付き・UTC）
 *     - 予測  (/api/forecast_today): "2026-08-19T19:00:00+09:00"（15分グリッド・JST）
 *   と粒度もオフセット表記も異なり、文字列キーが**一度も一致しない**。
 *   その結果、過去区間の予測は常に `existing === undefined` の else 分岐に落ち、
 *   keepForecast を無視して値付きのまま残っていた。
 *
 *   進行中の夜の pickPeak（actualOnly なし）は `menActual ?? menForecast` で最大を取るため、
 *   「実測ピーク 40人@22:00 / 過去の外れ予測 60人@21:00」なら
 *   「ピーク目安 21:00（男性30名 / 女性30名）」という**起きなかった数字**が
 *   SSR 本文（lib/store/ssrSummary.ts）とクライアントのチップの双方に出ていた。
 *
 * 修正: buildSeries は `existing` の有無に関わらず keepForecast を適用する。
 *       ただし実測が 1 点も無い場合（開店前など）は従来どおり全予測を残す。
 */

/** 本番 /api/range と同じ形（UTC・秒/マイクロ秒付き）の実測 ts を作る。 */
function actualTs(jstHour: number, jstMin: number, sec: number, micro: number): string {
  // JST -> UTC は -9h。2026-08-18 21:00 JST = 2026-08-18T12:00:00Z
  const utcHour = jstHour - 9;
  const hh = String(utcHour).padStart(2, "0");
  const mm = String(jstMin).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return `2026-08-18T${hh}:${mm}:${ss}.${micro}+00:00`;
}

/** 本番 /api/forecast_today と同じ形（JST・15分グリッド）の予測 ts を作る。 */
function forecastTs(jstHour: number, jstMin: number): string {
  const hh = String(jstHour).padStart(2, "0");
  const mm = String(jstMin).padStart(2, "0");
  return `2026-08-18T${hh}:${mm}:00+09:00`;
}

/**
 * 23:00 時点の進行中の夜を再現する。
 * - 実測: 21:00 は 10人、22:00 に実測ピーク 40人、22:45 は 30人
 * - 予測: 21:00 に外れた 60人（既に過去）、未来（23:15/23:30）は 20人程度
 */
function makeInProgressNight() {
  const actuals: RangePoint[] = [
    { ts: actualTs(21, 0, 25, 391249), men: 5, women: 5 },
    { ts: actualTs(22, 0, 22, 934326), men: 20, women: 20 },
    { ts: actualTs(22, 45, 27, 63933), men: 15, women: 15 },
  ];
  const forecasts: ForecastPoint[] = [
    // 過去（実測より前）＝もう答えが出ている外れ予測。ピークに使ってはいけない。
    { ts: forecastTs(21, 0), men_pred: 30, women_pred: 30 },
    { ts: forecastTs(22, 0), men_pred: 12, women_pred: 12 },
    // 未来（最終実測 22:45 より後）＝今夜これから来る想定。点線として残すべき。
    { ts: forecastTs(23, 15), men_pred: 10, women_pred: 10 },
    { ts: forecastTs(23, 30), men_pred: 11, women_pred: 12 },
  ];
  return { actuals, forecasts };
}

describe("buildSeries — 本番の ts 粒度差でも過去の予測を打ち消す（進行中の夜）", () => {
  it("実測 ts（マイクロ秒付きUTC）と予測 ts（15分グリッドJST）は文字列が一致しない（前提の固定）", () => {
    // この前提が崩れる（バックエンドが ts を揃える）と本バグの再現条件も変わる。
    expect(actualTs(21, 0, 25, 391249)).not.toBe(forecastTs(21, 0));
    expect(new Date(actualTs(21, 0, 25, 391249)).getTime()).toBeGreaterThan(
      new Date(forecastTs(21, 0)).getTime(),
    );
  });

  it("最終実測より過去の予測点は、同一 ts の実測が無くても値が null になる", () => {
    const { actuals, forecasts } = makeInProgressNight();
    const series = buildSeries(actuals, forecasts);

    const past2100 = series.find((p) => p.ts === forecastTs(21, 0));
    const past2200 = series.find((p) => p.ts === forecastTs(22, 0));
    expect(past2100?.menForecast).toBeNull();
    expect(past2100?.womenForecast).toBeNull();
    expect(past2200?.menForecast).toBeNull();
    expect(past2200?.womenForecast).toBeNull();
  });

  it("最終実測より未来の予測点は従来どおり残る（点線が消えない）", () => {
    const { actuals, forecasts } = makeInProgressNight();
    const series = buildSeries(actuals, forecasts);

    expect(series.find((p) => p.ts === forecastTs(23, 15))?.menForecast).toBe(10);
    expect(series.find((p) => p.ts === forecastTs(23, 30))?.womenForecast).toBe(12);
  });

  it("実測点は一切変化しない（点の数・実測値ともに保持）", () => {
    const { actuals, forecasts } = makeInProgressNight();
    const series = buildSeries(actuals, forecasts);

    // 実測3点 + 予測4点 = 7点（キーは一致しないので合流しない）。
    expect(series.length).toBe(actuals.length + forecasts.length);
    expect(series.find((p) => p.ts === actualTs(22, 0, 22, 934326))?.menActual).toBe(20);
    expect(series.find((p) => p.ts === actualTs(22, 0, 22, 934326))?.womenActual).toBe(20);
  });
});

describe("pickPeak（進行中の夜）— 過去の外れ予測をピークに拾わない", () => {
  it("実測ピーク 40人@22:00 を返し、過去の外れ予測 60人@21:00 に化けない", () => {
    const { actuals, forecasts } = makeInProgressNight();
    const peak = pickPeak(buildSeries(actuals, forecasts));

    expect(peak.peakTotal).toBe(40);
    expect(peak.peakTimeLabel).toBe("22:00");
    expect(peak.peakMen).toBe(20);
    expect(peak.peakWomen).toBe(20);
    // ピーク時刻は実測点の ts（秒付き）であり、予測グリッドの 21:00 ではない。
    expect(peak.peakTs).toBe(actualTs(22, 0, 22, 934326));
  });

  it("これから来る未来の予測ピークは従来どおり拾う（today の意図は維持）", () => {
    const { actuals } = makeInProgressNight();
    const forecasts: ForecastPoint[] = [
      // 過去の外れ予測（無視されるべき）
      { ts: forecastTs(21, 0), men_pred: 30, women_pred: 30 },
      // 未来に実測ピーク(40)を超える山が来る想定
      { ts: forecastTs(23, 30), men_pred: 35, women_pred: 35 },
    ];
    const peak = pickPeak(buildSeries(actuals, forecasts));

    expect(peak.peakTotal).toBe(70);
    expect(peak.peakTimeLabel).toBe("23:30");
    expect(peak.peakTs).toBe(forecastTs(23, 30));
  });
});

describe("buildSeries — 修正による副作用の防止", () => {
  it("実測が1点も無い（開店前）ときは全予測を残す＝グラフが空にならない", () => {
    const forecasts: ForecastPoint[] = [
      { ts: forecastTs(19, 0), men_pred: 2, women_pred: 10 },
      { ts: forecastTs(19, 15), men_pred: 3, women_pred: 12 },
      { ts: forecastTs(23, 30), men_pred: 20, women_pred: 25 },
    ];
    const series = buildSeries([], forecasts);

    expect(series.length).toBe(3);
    for (const f of forecasts) {
      expect(series.find((p) => p.ts === f.ts)?.menForecast).toBe(f.men_pred);
      expect(series.find((p) => p.ts === f.ts)?.womenForecast).toBe(f.women_pred);
    }
  });

  it("overlayAllForecast:true（完了夜の答え合わせ）は過去の予測もすべて残す", () => {
    const { actuals, forecasts } = makeInProgressNight();
    const series = buildSeries(actuals, forecasts, true);

    for (const f of forecasts) {
      expect(series.find((p) => p.ts === f.ts)?.menForecast).toBe(f.men_pred);
      expect(series.find((p) => p.ts === f.ts)?.womenForecast).toBe(f.women_pred);
    }
  });

  it("最終実測とちょうど同時刻の予測は過去扱い（t > lastActual のみ未来）", () => {
    const actuals: RangePoint[] = [{ ts: "2026-08-18T13:00:00+09:00", men: 10, women: 10 }];
    const forecasts: ForecastPoint[] = [
      { ts: "2026-08-18T13:00:00+09:00", men_pred: 99, women_pred: 99 },
      { ts: "2026-08-18T13:15:00+09:00", men_pred: 11, women_pred: 12 },
    ];
    const series = buildSeries(actuals, forecasts);

    // ts が完全一致するケース（既存の existing 分岐）も従来どおり null 化される。
    const same = series.find((p) => p.ts === "2026-08-18T13:00:00+09:00");
    expect(same?.menActual).toBe(10);
    expect(same?.menForecast).toBeNull();
    expect(series.find((p) => p.ts === "2026-08-18T13:15:00+09:00")?.menForecast).toBe(11);
  });
});
