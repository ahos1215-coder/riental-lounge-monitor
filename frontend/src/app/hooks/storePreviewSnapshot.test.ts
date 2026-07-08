import { describe, it, expect } from "vitest";
import {
  buildSeries,
  computeNightBaseDate,
  computeSelectedNightBaseDate,
  computeNightWindowFromBaseDate,
  isWithinNight,
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
