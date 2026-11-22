// 店舗ページ「混みやすい曜日・時間帯」セクションの集計と文章生成（純関数）。
// 入力は scripts/build-store-trends.mjs が事前生成した 1 店舗ぶんのエントリ。
// 文章は固定テンプレート＋数値のみ（LLM 文は使わない）。生成 JSON は import しない
// （サーバー専用のデータ取得は storeTrendsData.ts 側）。

export type StoreTrendCell = {
  /** 曜日 0=月 … 6=日（夜基準: 0:00〜5:59 は前日の夜の曜日） */
  d: number;
  /** 時間帯 */
  h: number;
  /** 平均混雑度 0..1 */
  o: number;
  /** 平均女性比率 0..1 */
  f: number;
  /** サンプル数（5分ごと） */
  n: number;
};

export type StoreTrendEntry = {
  weeks: string[];
  periodStart: string;
  periodEnd: string;
  cells: StoreTrendCell[];
};

export type StoreTrendSlot = { d: number; h: number; o: number; n: number };
export type StoreTrendHour = { h: number; o: number };

export type StoreTrendSummary = {
  weeksUsed: number;
  periodStart: string;
  periodEnd: string;
  busiestDays: number[];
  quietestDay: number | null;
  busiestSlots: StoreTrendSlot[];
  weekendPeakHour: StoreTrendHour | null;
  weekendQuietHour: StoreTrendHour | null;
  /** weekendQuietHour.o / weekendPeakHour.o（どちらかが無ければ null） */
  quietRatio: number | null;
  weekdayToWeekendRatio: number | null;
  femaleRatioWeekend: number | null;
  femaleRatioWeekday: number | null;
};

export const MIN_CELL_SAMPLES = 12;
export const MIN_WEEKS = 2;
export const STALE_DAYS = 21;
/** 金・土 */
const WEEKEND_DAYS: ReadonlySet<number> = new Set([4, 5]);
export const DAY_LABELS = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"] as const;
/** 夜の時間帯の並び順（storeTrendsCore.mjs の HEATMAP_HOURS と同じ） */
export const HEATMAP_HOURS: readonly number[] = [19, 20, 21, 22, 23, 0, 1, 2, 3, 4];

const DAY_MS = 24 * 60 * 60 * 1000;

function hourOrder(h: number): number {
  const i = HEATMAP_HOURS.indexOf(h);
  return i < 0 ? 999 : i;
}

/** now の JST カレンダー日付を UTC 0:00 のミリ秒で返す */
function jstDayStartMs(now: Date): number {
  const shifted = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate());
}

function weightedMean(items: { v: number; w: number }[]): number | null {
  let sw = 0;
  let sv = 0;
  for (const it of items) {
    sw += it.w;
    sv += it.v * it.w;
  }
  return sw > 0 ? sv / sw : null;
}

/** 人数加重（o·n）の女性比率。分母 0 なら null。 */
function peopleWeightedFemale(cells: StoreTrendCell[]): number | null {
  let den = 0;
  let num = 0;
  for (const c of cells) {
    if (!(c.o > 0)) continue;
    den += c.o * c.n;
    num += c.f * c.o * c.n;
  }
  return den > 0 ? num / den : null;
}

export function summarizeStoreTrend(
  entry: StoreTrendEntry | null | undefined,
  opts: { now: Date },
): StoreTrendSummary | null {
  if (!entry || !Array.isArray(entry.weeks) || !Array.isArray(entry.cells)) return null;
  if (entry.weeks.length < MIN_WEEKS) return null;

  const newestMs = Date.parse(`${entry.weeks[0]}T00:00:00Z`);
  if (!Number.isFinite(newestMs)) return null;
  if ((jstDayStartMs(opts.now) - newestMs) / DAY_MS > STALE_DAYS) return null;

  const valid = entry.cells.filter(
    (c) => c && Number.isFinite(c.o) && Number.isFinite(c.n) && c.n >= MIN_CELL_SAMPLES,
  );
  if (valid.length === 0) return null;

  // 曜日別平均
  const dayAvg: { d: number; o: number }[] = [];
  for (let d = 0; d < 7; d++) {
    const o = weightedMean(valid.filter((c) => c.d === d).map((c) => ({ v: c.o, w: c.n })));
    if (o != null) dayAvg.push({ d, o });
  }
  const byBusy = [...dayAvg].sort((a, b) => b.o - a.o || a.d - b.d);
  const busiestDays = byBusy.slice(0, 2).map((x) => x.d);
  let quietestDay: number | null = null;
  if (dayAvg.length >= 3) {
    const lowest = [...dayAvg].sort((a, b) => a.o - b.o || a.d - b.d)[0];
    if (!busiestDays.includes(lowest.d)) quietestDay = lowest.d;
  }

  // 特に混んだ時間帯
  const busiestSlots = valid
    .filter((c) => c.o > 0)
    .sort((a, b) => b.o - a.o || b.n - a.n || a.d - b.d || hourOrder(a.h) - hourOrder(b.h))
    .slice(0, 3)
    .map((c) => ({ d: c.d, h: c.h, o: c.o, n: c.n }));

  // 金・土の時間帯別
  const weekendCells = valid.filter((c) => WEEKEND_DAYS.has(c.d));
  const weekdayCells = valid.filter((c) => !WEEKEND_DAYS.has(c.d));
  const hourAgg: StoreTrendHour[] = [];
  for (const h of HEATMAP_HOURS) {
    const hc = weekendCells.filter((c) => c.h === h);
    const sumN = hc.reduce((s, c) => s + c.n, 0);
    if (sumN < MIN_CELL_SAMPLES) continue;
    const o = weightedMean(hc.map((c) => ({ v: c.o, w: c.n })));
    if (o != null) hourAgg.push({ h, o });
  }
  let weekendPeakHour: StoreTrendHour | null = null;
  for (const x of hourAgg) {
    if (weekendPeakHour == null || x.o > weekendPeakHour.o) weekendPeakHour = x;
  }
  // 「比較的空いている時間」はピークより前（夜の早い時間）からだけ選ぶ。
  // 閉店間際（4時台など）がいちばん空いていても「何時に行くか」の参考にならないため。
  let weekendQuietHour: StoreTrendHour | null = null;
  if (weekendPeakHour) {
    const peakIdx = hourOrder(weekendPeakHour.h);
    for (const x of hourAgg) {
      if (hourOrder(x.h) >= peakIdx) continue;
      if (weekendQuietHour == null || x.o < weekendQuietHour.o) weekendQuietHour = x;
    }
  }
  const quietRatio =
    weekendPeakHour && weekendQuietHour && weekendPeakHour.o > 0
      ? weekendQuietHour.o / weekendPeakHour.o
      : null;

  const weekendAvg = weightedMean(weekendCells.map((c) => ({ v: c.o, w: c.n })));
  const weekdayAvg = weightedMean(weekdayCells.map((c) => ({ v: c.o, w: c.n })));
  const weekdayToWeekendRatio =
    weekendAvg != null && weekdayAvg != null && weekendAvg > 0 ? weekdayAvg / weekendAvg : null;

  return {
    weeksUsed: entry.weeks.length,
    periodStart: entry.periodStart,
    periodEnd: entry.periodEnd,
    busiestDays,
    quietestDay,
    busiestSlots,
    weekendPeakHour,
    weekendQuietHour,
    quietRatio,
    weekdayToWeekendRatio,
    femaleRatioWeekend: peopleWeightedFemale(weekendCells),
    femaleRatioWeekday: peopleWeightedFemale(weekdayCells),
  };
}

/** 「約◯割」表記。1割未満は「1割未満」。 */
function warite(ratio: number): string {
  const k = Math.round(ratio * 10);
  return k < 1 ? "1割未満" : `約${k}割`;
}

export function buildStoreTrendSentences(
  summary: StoreTrendSummary,
  opts: { showGenderRatio: boolean },
): string[] {
  const out: string[] = [];

  if (summary.busiestDays.length >= 2) {
    out.push(
      `混みやすい曜日は${DAY_LABELS[summary.busiestDays[0]]}・${DAY_LABELS[summary.busiestDays[1]]}でした。`,
    );
  } else if (summary.busiestDays.length === 1) {
    out.push(`混みやすい曜日は${DAY_LABELS[summary.busiestDays[0]]}でした。`);
  }

  if (summary.busiestSlots.length > 0) {
    const slots = summary.busiestSlots.map((s) => `${DAY_LABELS[s.d]}${s.h}時台`);
    out.push(`特に混んだ時間帯は${slots.join("、")}です。`);
  }

  const { weekendQuietHour: q, weekendPeakHour: p, quietRatio } = summary;
  if (q && p && q.h !== p.h && quietRatio != null && quietRatio < 0.6) {
    out.push(
      `金・土の夜でも${q.h}時台は比較的空いていて、ピーク（${p.h}時台）の${warite(quietRatio)}の混み具合です。`,
    );
  }

  if (summary.weekdayToWeekendRatio != null) {
    const r = summary.weekdayToWeekendRatio;
    out.push(
      r >= 0.9
        ? "日〜木曜の夜も、金・土と同じくらい混みます。"
        : `日〜木曜の夜の混み具合は、金・土の${warite(r)}です。`,
    );
  }

  if (summary.quietestDay != null) {
    out.push(`比較的落ち着いているのは${DAY_LABELS[summary.quietestDay]}の夜です。`);
  }

  if (opts.showGenderRatio) {
    const w = summary.femaleRatioWeekend;
    const d = summary.femaleRatioWeekday;
    if (w != null && d != null) {
      out.push(
        `女性比率の平均は、金・土の夜が約${Math.round(w * 100)}%、日〜木曜の夜が約${Math.round(d * 100)}%でした。`,
      );
    } else if (w != null) {
      out.push(`金・土の夜の女性比率は平均約${Math.round(w * 100)}%でした。`);
    } else if (d != null) {
      out.push(`日〜木曜の夜の女性比率は平均約${Math.round(d * 100)}%でした。`);
    }
  }

  return out;
}

/** 例: 2026/10/22〜11/17（年をまたぐ場合は 2025/12/24〜2026/01/20） */
export function formatTrendPeriod(
  summary: Pick<StoreTrendSummary, "periodStart" | "periodEnd">,
): string {
  const s = summary.periodStart.replace(/-/g, "/");
  const e = summary.periodEnd.replace(/-/g, "/");
  const sameYear = s.slice(0, 4) === e.slice(0, 4);
  return `${s}〜${sameYear ? e.slice(5) : e}`;
}

/**
 * 集計元の説明（見出し下の1行）。週次ファイルが欠けた週（例: 集計PCが止まった週）があると
 * 期間が採用週数より長くなるので、そのときは「直近N週」と書かず「〜のうちN週分」と書く。
 */
export function formatTrendBasis(
  summary: Pick<StoreTrendSummary, "weeksUsed" | "periodStart" | "periodEnd">,
): string {
  const period = formatTrendPeriod(summary);
  const s = Date.parse(`${summary.periodStart}T00:00:00Z`);
  const e = Date.parse(`${summary.periodEnd}T00:00:00Z`);
  const spanDays = Number.isFinite(s) && Number.isFinite(e) ? Math.round((e - s) / DAY_MS) + 1 : null;
  if (spanDays != null && spanDays > summary.weeksUsed * 7 + 3) {
    return `${period}のうち${summary.weeksUsed}週分の実測から集計`;
  }
  return `直近${summary.weeksUsed}週（${period}）の実測から集計`;
}
