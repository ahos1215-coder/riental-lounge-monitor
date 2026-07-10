import { describe, it, expect } from "vitest";
import {
  buildSeries,
  computeInitialRefreshDelayMs,
  computeNightBaseDate,
  computeSelectedNightBaseDate,
  computeNightWindowFromBaseDate,
  INITIAL_REFRESH_DELAY_MAX_MS,
  INITIAL_REFRESH_DELAY_MIN_MS,
  isNightCompleted,
  isWithinNight,
  nightDateYYYYMMDD,
  parseRangePoints,
  hasSeriesData,
  formatYMD,
  addDays,
  type RangePoint,
  type ForecastPoint,
} from "./storePreviewSnapshot";

/**
 * 昨日モード（および先週/カスタム）のグラフ描画リグレッションテスト。
 *
 * 経緯: 「昨日」タブでグラフが空表示になる不具合の再発防止。昨日モードは予測 API を
 * 叩かず /api/range の実測のみを描く。実測点が正しく夜窓に入っていれば、実線（実測）が
 * 必ず描かれること（＝空グラフにならないこと）を保証する。
 */

// 指定 JST 夜日付（19:00-翌05:00）の実測 range を 15 分刻みで生成する。
function makeNightActuals(baseYmd: string): RangePoint[] {
  const out: RangePoint[] = [];
  const start = new Date(`${baseYmd}T19:00:00+09:00`);
  for (let i = 0; i <= 40; i += 1) {
    const t = new Date(start.getTime() + i * 15 * 60 * 1000);
    out.push({ ts: t.toISOString(), men: 10 + i, women: 20 + i, total: 30 + 2 * i });
  }
  return out;
}

describe("storePreviewSnapshot — yesterday-mode series", () => {
  it("builds solid actual lines for yesterday's night window (chart must not be empty)", () => {
    const now = new Date();
    const baseDate = computeSelectedNightBaseDate("yesterday", "", now);
    const baseYmd = formatYMD(baseDate);
    const nightWindow = computeNightWindowFromBaseDate(baseDate);

    // バックエンドが [from, to] = [昨日, 今日] のスパンで返す実測。
    const rangeJson = { ok: true, rows: makeNightActuals(baseYmd) };
    const allRangePoints = parseRangePoints(rangeJson);
    const rangePoints = allRangePoints.filter((p) => isWithinNight(p.ts, nightWindow));

    // 昨日モードのフック挙動: forecast は取得しないので buildSeries(range, [])。
    const series = buildSeries(rangePoints, []);

    expect(rangePoints.length).toBeGreaterThan(0);
    expect(series.length).toBe(rangePoints.length);
    // 実線（実測）が男女とも描画対象として存在する＝グラフが空にならない。
    expect(series.some((p) => p.menActual !== null)).toBe(true);
    expect(series.some((p) => p.womenActual !== null)).toBe(true);
    expect(hasSeriesData(series)).toBe(true);
  });

  it("derives stable day-boundary from/to for yesterday (CDN-cacheable, no per-minute stamp)", () => {
    const now = new Date();
    const baseDate = computeSelectedNightBaseDate("yesterday", "", now);
    const fromYmd = formatYMD(baseDate);
    const toYmd = formatYMD(addDays(baseDate, 1));
    const todayBase = computeNightBaseDate(now);

    // from/to は YYYY-MM-DD の日境界のみ（分秒を含まない）＝同一日の全訪問で同じ URL。
    expect(fromYmd).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(toYmd).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(fromYmd < toYmd).toBe(true);
    // 昨日は今日の夜日付のちょうど 1 日前。
    expect(fromYmd).toBe(formatYMD(addDays(todayBase, -1)));
  });

  it("keeps actual + forecast overlay when forecast extends beyond the last actual (today-mode contract)", () => {
    // buildSeries は「最後の実測より未来」の予測のみ点線として残す（過去区間の二重描画防止）。
    // today モードで実測の先に予測が伸びるケースでは、実線＋点線が両立することを保証する。
    const t = (min: number) =>
      new Date(Date.UTC(2026, 6, 7, 10, 0, 0) + min * 60_000).toISOString();
    const actuals: RangePoint[] = [
      { ts: t(0), men: 5, women: 8 },
      { ts: t(15), men: 7, women: 10 },
      { ts: t(30), men: 9, women: 12 },
    ];
    const forecasts: ForecastPoint[] = [
      // 実測と重なる区間（過去）→ 点線は描かれない
      { ts: t(30), men_pred: 9, women_pred: 12 },
      // 実測より未来 → 点線として描かれる
      { ts: t(45), men_pred: 11, women_pred: 14 },
      { ts: t(60), men_pred: 13, women_pred: 16 },
    ];
    const series = buildSeries(actuals, forecasts);

    expect(series.some((p) => p.menActual !== null)).toBe(true);
    // 未来区間の予測（点線）が存在する＝実測＋予測オーバーレイが成立。
    const forecastPts = series.filter((p) => p.menForecast !== null || p.womenForecast !== null);
    expect(forecastPts.length).toBe(2);
    // 過去（実測と重なる）区間には予測点線を引かない。
    const overlapPt = series.find((p) => p.ts === t(30));
    expect(overlapPt?.menForecast).toBeNull();
  });
});

/**
 * 完了済みの夜の答え合わせオーバーレイ機能の回帰テスト。
 *
 * 経緯: 完了済みの夜（昨日/先週/カスタム過去日、または「今日」モードで夜が既に終わった
 * 05:00-19:00 の間）は、その夜に実際配信されていた予測のスナップショットを
 * /api/forecast_snapshot から取得し、実測(実線)の上に予測(点線)を夜全体で重ねて
 * 表示する。この重ね描画には buildSeries の overlayAllForecast:true を使う
 * （デフォルトの false は「実測より未来の区間だけ点線を残す」today 進行中の挙動）。
 */
describe("storePreviewSnapshot — night completion helpers", () => {
  it("nightDateYYYYMMDD formats the night's JST base date as YYYYMMDD (snapshot storage key)", () => {
    const baseDate = new Date(2026, 6, 8); // 2026-07-08 (JS month is 0-indexed)
    expect(nightDateYYYYMMDD(baseDate)).toBe("20260708");
  });

  it("nightDateYYYYMMDD pads single-digit month/day", () => {
    const baseDate = new Date(2026, 0, 5); // 2026-01-05
    expect(nightDateYYYYMMDD(baseDate)).toBe("20260105");
  });

  it("isNightCompleted is false while now is still within the night window", () => {
    const baseDate = computeSelectedNightBaseDate("yesterday", "", new Date());
    const window = computeNightWindowFromBaseDate(baseDate);
    // window の終わり(翌05:00)の1分前 = まだ完了していない
    const justBeforeEnd = new Date(window.end.getTime() - 60_000);
    expect(isNightCompleted(baseDate, justBeforeEnd)).toBe(false);
  });

  it("isNightCompleted is true once now is at/after the night window end (05:00 JST)", () => {
    const baseDate = computeSelectedNightBaseDate("yesterday", "", new Date());
    const window = computeNightWindowFromBaseDate(baseDate);
    expect(isNightCompleted(baseDate, window.end)).toBe(true);
    const justAfterEnd = new Date(window.end.getTime() + 60_000);
    expect(isNightCompleted(baseDate, justAfterEnd)).toBe(true);
  });

  it("a 'yesterday' night is always completed relative to any current time (regression: overlay must fire for 昨日)", () => {
    const now = new Date();
    const baseDate = computeSelectedNightBaseDate("yesterday", "", now);
    expect(isNightCompleted(baseDate, now)).toBe(true);
  });
});

describe("storePreviewSnapshot — buildSeries overlayAllForecast (completed-night overlay)", () => {
  const t = (min: number) =>
    new Date(Date.UTC(2026, 6, 7, 10, 0, 0) + min * 60_000).toISOString();

  function makeActualsAndForecasts() {
    // 実測は夜の前半だけ（後半はまだ実測データが来ていない想定でも良い）。
    const actuals: RangePoint[] = [
      { ts: t(0), men: 5, women: 8 },
      { ts: t(15), men: 7, women: 10 },
      { ts: t(30), men: 9, women: 12 },
    ];
    // 予測はその夜全体（実測と重なる過去区間 + 実測より未来の区間）を含む。
    const forecasts: ForecastPoint[] = [
      { ts: t(0), men_pred: 4, women_pred: 7 },
      { ts: t(15), men_pred: 6, women_pred: 9 },
      { ts: t(30), men_pred: 8, women_pred: 11 },
      { ts: t(45), men_pred: 11, women_pred: 14 },
      { ts: t(60), men_pred: 13, women_pred: 16 },
    ];
    return { actuals, forecasts };
  }

  it("overlayAllForecast:true keeps every forecast point (even past/overlapping ones) — nothing nulled", () => {
    const { actuals, forecasts } = makeActualsAndForecasts();
    const series = buildSeries(actuals, forecasts, true);

    // すべての予測点で menForecast/womenForecast が null にならず値を保持している。
    for (const f of forecasts) {
      const pt = series.find((p) => p.ts === f.ts);
      expect(pt).toBeDefined();
      expect(pt?.menForecast).toBe(f.men_pred);
      expect(pt?.womenForecast).toBe(f.women_pred);
    }
    // 実測(実線)も同時に残っている＝実測+予測オーバーレイが両立。
    expect(series.find((p) => p.ts === t(0))?.menActual).toBe(5);
    expect(series.find((p) => p.ts === t(30))?.menActual).toBe(9);
  });

  it("overlayAllForecast:false (default) preserves the existing isFutureOnly behavior (past overlap nulled)", () => {
    const { actuals, forecasts } = makeActualsAndForecasts();
    const seriesDefault = buildSeries(actuals, forecasts);
    const seriesExplicitFalse = buildSeries(actuals, forecasts, false);

    for (const series of [seriesDefault, seriesExplicitFalse]) {
      // 実測と重なる過去区間（t(0), t(15), t(30)）は予測が null化される。
      expect(series.find((p) => p.ts === t(0))?.menForecast).toBeNull();
      expect(series.find((p) => p.ts === t(15))?.menForecast).toBeNull();
      expect(series.find((p) => p.ts === t(30))?.menForecast).toBeNull();
      // 実測より未来の区間（t(45), t(60)）は予測が残る。
      expect(series.find((p) => p.ts === t(45))?.menForecast).toBe(11);
      expect(series.find((p) => p.ts === t(60))?.menForecast).toBe(13);
    }
  });
});

/**
 * useStorePreviewData の「initialSnapshot 消費直後は最初のバックグラウンド再取得を
 * 60-90s 遅らせる」ロジックの純粋部分（遅延ms計算）の回帰テスト。
 *
 * 経緯: page.tsx の SSR initialSnapshot はサーバー・クライアント双方が同じ店舗の
 * forecast_today/forecast_snapshot を back-to-back に二重フェッチしていた
 * （バックエンド側の一時的な輻輳・無駄な ML 再計算の原因）。initialSnapshot をその
 * ままマウント直後にもう一度取り直すのを避けるため、最初の1回だけ遅延させる。
 * コールド CSR（initialSnapshot 無し）の挙動は絶対に変えてはならない（0ms=即時実行）。
 */
describe("storePreviewSnapshot — computeInitialRefreshDelayMs (seeded-delay logic)", () => {
  it("returns 0 (no delay) when there is no usable initial seed — cold CSR path must not slow down", () => {
    expect(computeInitialRefreshDelayMs(false)).toBe(0);
    expect(computeInitialRefreshDelayMs(false, () => 0)).toBe(0);
    expect(computeInitialRefreshDelayMs(false, () => 0.999)).toBe(0);
  });

  it("returns the minimum delay when random() is 0", () => {
    expect(computeInitialRefreshDelayMs(true, () => 0)).toBe(INITIAL_REFRESH_DELAY_MIN_MS);
  });

  it("returns a value strictly below the maximum delay when random() approaches 1", () => {
    const delay = computeInitialRefreshDelayMs(true, () => 0.999999);
    expect(delay).toBeGreaterThanOrEqual(INITIAL_REFRESH_DELAY_MIN_MS);
    expect(delay).toBeLessThan(INITIAL_REFRESH_DELAY_MAX_MS);
  });

  it("stays within the documented [60s, 90s) range for arbitrary random values", () => {
    for (const r of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999]) {
      const delay = computeInitialRefreshDelayMs(true, () => r);
      expect(delay).toBeGreaterThanOrEqual(INITIAL_REFRESH_DELAY_MIN_MS);
      expect(delay).toBeLessThan(INITIAL_REFRESH_DELAY_MAX_MS);
    }
  });

  it("clamps out-of-range random() implementations defensively (NaN/negative/>1)", () => {
    expect(computeInitialRefreshDelayMs(true, () => Number.NaN)).toBe(INITIAL_REFRESH_DELAY_MIN_MS);
    expect(computeInitialRefreshDelayMs(true, () => -1)).toBe(INITIAL_REFRESH_DELAY_MIN_MS);
    expect(computeInitialRefreshDelayMs(true, () => 5)).toBeLessThan(INITIAL_REFRESH_DELAY_MAX_MS + 1);
  });
});
