// frontend/src/lib/compare/compareSeries.ts
//
// /compare（店舗比較）のチャート用データを組み立てる純粋関数。React も Recharts も
// import しない（compare-client.tsx から切り出して単体テストできるようにするため）。
//
// 経緯（2026-08-21 外部レビュー F7 / F10）:
//  F7: 各店舗の実測 ts は「秒・マイクロ秒付き」で店舗ごとにバラバラ（収集は5分おきだが、
//      実際に書かれる ts は 20:40:12.481 / 20:40:37.902 のように店ごとにズレる）。
//      旧実装はその **ts の完全一致** を鍵に全店の和集合を作っていたため、ある行には
//      A 店の値しか無く、次の行には B 店の値しか無い、という歯抜けの表になっていた。
//      線は connectNulls=false / dot=false なので、歯抜け＝線が1点ずつ途切れて
//      「実測線がほぼ見えない」状態だった（本番データで時刻の一致は200件中0件）。
//      → **5分スロットに丸めてから** マージする。丸めた時刻を鍵にすれば全店が同じ点に乗る。
//  F10: 日付・夜窓を指定せず「最新200件」を全部描いていたため、20:40 / 05:00 / 13:20 /
//      21:40 のように **複数の夜と日中が混ざった** 折れ線になっていた。
//      → 店舗ページと同じ夜窓（19:00-翌05:00 JST / lib/date/nightWindow.ts）で絞る。
import type { NightWindowRange } from "@/lib/date/nightWindow";
import { isWithinNight } from "@/lib/date/nightWindow";
import { rowTotalOrNull, type RangeRow } from "@/lib/range/rangeRows";
import type { ForecastPoint } from "@/lib/forecast/types";

/** チャート1点（ts は epoch ms。X軸を「時刻に比例した数値軸」にするための鍵）。 */
export type ComparePoint = { ts: number; total: number };

/**
 * マージの丸め幅。実測の収集間隔（5分）に合わせる。
 * 予測は 15分グリッド（:00/:15/:30/:45）なので、5分スロットに丸めても位置は変わらない。
 */
export const COMPARE_SLOT_MS = 5 * 60 * 1000;

/** epoch ms を 5分スロットの開始時刻に切り下げる（負値・非有限値はそのまま NaN 扱い）。 */
export function floorToCompareSlot(ts: number, slotMs: number = COMPARE_SLOT_MS): number {
  if (!Number.isFinite(ts) || !Number.isFinite(slotMs) || slotMs <= 0) return NaN;
  return Math.floor(ts / slotMs) * slotMs;
}

/** 人数 → 表示値（相席屋は席の埋まり具合%）に変換する関数。 */
export type ToDisplayValue = (total: number) => number;

/**
 * /api/range の行 → 実測系列。夜窓の外（別の夜・日中）の行は捨てる。
 * 合計は lib/range の rowTotalOrNull（total 優先、無ければ men+women）に一本化。
 */
export function buildActualSeries(
  rows: RangeRow[],
  nightWindow: NightWindowRange,
  toValue: ToDisplayValue,
): ComparePoint[] {
  const out: ComparePoint[] = [];
  for (const r of rows) {
    if (!r?.ts || !isWithinNight(r.ts, nightWindow)) continue;
    const ts = new Date(r.ts).getTime();
    if (!Number.isFinite(ts)) continue;
    out.push({ ts, total: toValue(rowTotalOrNull(r) ?? 0) });
  }
  return out.sort((a, b) => a.ts - b.ts);
}

/**
 * /api/forecast_today_multi の行 → 予測系列。
 * total_pred が null の行（履歴不足で予測不能な店舗）は除外する
 * （0 埋めすると「今夜ずっと0人」の平坦な予測ラインとして誤表示されるため）。
 * 夜窓の外の点も捨てる（05:00-19:00 に開くと、まだ来ていない今夜の予測が
 * 「昨夜の実測」の右隣に生えて、1本の連続した線に見えてしまう）。
 */
export function buildForecastSeries(
  rows: ForecastPoint[],
  nightWindow: NightWindowRange,
  toValue: ToDisplayValue,
): ComparePoint[] {
  const out: ComparePoint[] = [];
  for (const r of rows) {
    if (!r?.ts || typeof r.total_pred !== "number") continue;
    if (!isWithinNight(r.ts, nightWindow)) continue;
    const ts = new Date(r.ts).getTime();
    if (!Number.isFinite(ts)) continue;
    out.push({ ts, total: toValue(r.total_pred) });
  }
  return out.sort((a, b) => a.ts - b.ts);
}

export type CompareStoreSeries = {
  sparkline: ComparePoint[];
  forecast: ComparePoint[];
};

/** Recharts に渡す1行（`ts` = スロット開始の epoch ms、`label` = HH:MM 表示）。 */
export type CompareChartRow = Record<string, unknown> & { ts: number; label: string };

/**
 * 全店舗の系列を **5分スロット** でマージして Recharts 用の行配列にする。
 *
 * 同一スロットに複数点がある場合は「後の ts が勝つ」（実測が5分に2回書かれた場合の保険。
 * 本番では基本的に発生しない）。
 */
export function buildCompareChartData(args: {
  slugs: string[];
  seriesBySlug: Record<string, CompareStoreSeries | undefined>;
  formatTime: (ts: number) => string;
  slotMs?: number;
}): CompareChartRow[] {
  const { slugs, seriesBySlug, formatTime } = args;
  const slotMs = args.slotMs ?? COMPARE_SLOT_MS;

  // slot -> { key -> {ts, value} }（同一スロット内は ts が大きい方を採用）
  const bySlot = new Map<number, Map<string, { ts: number; value: number }>>();

  const put = (key: string, points: ComparePoint[]) => {
    for (const p of points) {
      const slot = floorToCompareSlot(p.ts, slotMs);
      if (!Number.isFinite(slot)) continue;
      let cell = bySlot.get(slot);
      if (!cell) {
        cell = new Map();
        bySlot.set(slot, cell);
      }
      const prev = cell.get(key);
      if (!prev || p.ts >= prev.ts) cell.set(key, { ts: p.ts, value: p.total });
    }
  };

  for (const slug of slugs) {
    const s = seriesBySlug[slug];
    if (!s) continue;
    put(`actual_${slug}`, s.sparkline);
    put(`forecast_${slug}`, s.forecast);
  }

  return Array.from(bySlot.keys())
    .sort((a, b) => a - b)
    .map((slot) => {
      const row: CompareChartRow = { ts: slot, label: formatTime(slot) };
      const cell = bySlot.get(slot);
      if (cell) for (const [key, v] of cell) row[key] = v.value;
      return row;
    });
}

const WEEKDAY_JA = ["日", "月", "火", "水", "木", "金", "土"];

/**
 * 表示中の夜の見出し（例: 「8/20(木) 19:00 → 翌05:00」）。
 * baseDate は JST の Y/M/D を運ぶ値なので getMonth/getDate/getDay だけで読む
 * （lib/date/nightWindow.ts の computeNightBaseDate と同じ約束）。
 */
export function nightWindowLabel(baseDate: Date): string {
  const m = baseDate.getMonth() + 1;
  const d = baseDate.getDate();
  const w = WEEKDAY_JA[baseDate.getDay()] ?? "";
  return `${m}/${d}(${w}) 19:00 → 翌05:00`;
}

const HOUR_MS = 60 * 60 * 1000;

/**
 * 1時間刻みの目盛り（最初の「ちょうどの時」から最後まで）。
 * components/TimelineChart.tsx の hourlyTicks と同じ考え方（時刻に比例した数値軸で、
 * 目盛りが半端な時刻に落ちないようにする）。
 */
export function compareHourlyTicks(minTs: number, maxTs: number): number[] {
  if (!Number.isFinite(minTs) || !Number.isFinite(maxTs) || maxTs <= minTs) return [];
  const first = Math.ceil(minTs / HOUR_MS) * HOUR_MS;
  const ticks: number[] = [];
  for (let t = first; t <= maxTs; t += HOUR_MS) ticks.push(t);
  return ticks;
}
