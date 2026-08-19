// frontend/src/lib/area/areaLiveSummary.ts
//
// エリアハブページ（/area/[area]）に「各店の混雑（実測）」をサーバー側HTMLの
// テキストとして出すための純粋関数。
//
// 背景（SEO Phase3-D）: エリアページは静的文言中心のテンプレで、単独店舗エリア9件は
// 互いに地名しか違わない「ほぼ同一ページ」になっていた（薄いページ量産のリスク）。
// ここで各店の実測値（その夜のピーク・時間帯別の推移・進行中なら直近値・最終計測時刻）を
// テキスト化して載せることで、エリアごとに内容が異なる・利用者にも意味のあるページにする。
//
// データ源は店舗ページ（store/[id]/page.tsx）と同じ「夜窓で区切った /api/range（from/to + limit=240）」。
// URL が同一なので Next の fetch キャッシュとバックエンドの per-store キャッシュを店舗ページと共有し、
// 追加負荷はほぼ無い。取得できなければ呼び出し側がブロックごと省く。
//
// 総点検5巡目（2026-08-19）で直した点:
//  - 旧版は「直近48行（=4時間）」しか見ておらず、昼間の再生成では 1〜4時台だけが“その夜の推移”に
//    なっていた／最終ティック（04:55 閉店）が 0 人だと店行ごと消えていた。→ 夜窓全体を対象にし、
//    「いま」は進行中の夜だけ・完了した夜は「ピーク」と「時間帯別」で語る。
//
// 厳守事項（lib/store/ssrSummary.ts と同じ）:
//  - 実データのみ。無い値は出さない（0人・--:-- 等の「空箱」を作らない）
//  - 相席屋（isPercentCrowdBrand）は在店人数を公開していないため、人数は一切出さず % のみ
//  - 時刻は JST 絶対時刻（「◯分前」は ISR で嘘になるため使わない）
import {
  buildStoreFullName,
  isPercentCrowdBrand,
  seatFullnessPercent,
  seatFullnessPercentOfTotal,
  type StoreMeta,
} from "@/app/config/stores";
import {
  computeNightBaseDate,
  computeNightWindowFromBaseDate,
  formatNowHmJst,
  isNightCompleted,
  isWithinNight,
} from "@/lib/date/nightWindow";
import { orderedRangeRows, type StoreCardRangeRow } from "@/lib/storeCardRangeSparkline";
import { rowTotalOrNull, toNonNegIntOrNull } from "@/lib/range/rangeRows";
import { MIN_HOURLY_BUCKETS, rollUpByNightHour } from "@/lib/store/nightHourlyRollup";

// 時間帯別ロールアップと最小バケット数は lib/store/nightHourlyRollup.ts が正本
// （店舗ページ ssrSummary.ts と共有）。

export type AreaStoreLiveLine = {
  slug: string;
  /** 「オリエンタルラウンジ 長崎」など */
  storeName: string;
  /**
   * 進行中の夜のみ: 「男性12人 / 女性9人（男57% / 女43%）」または「席の埋まり具合 約35%（男性30% / 女性40%）」。
   * 完了した夜、または直近ティックが 0 人のときは null（閉店間際の残留人数を「いま」と言わない）。
   */
  nowText: string | null;
  /** 「22:15 に最多（男性30人 / 女性28人）」/ 相席屋は「22:15 に最多（席の埋まり具合 約85%）」。実測ゼロなら null */
  peakText: string | null;
  /** 「20時 18人 / 21時 25人 / 22時 31人」。2時間分未満なら null */
  hourlyText: string | null;
  /** 「23:45 時点」（進行中）/「最終計測 04:55」（完了）。ts が読めなければ null */
  updatedText: string | null;
};

export type AreaLiveSummary = {
  /** 「今夜」（進行中の夜）or「直近の営業夜（8/18）」（05:00〜19:00 の間） */
  nightLabel: string;
  /** その夜が終わっているか（見出し・注記の出し分け用） */
  completed: boolean;
  lines: AreaStoreLiveLine[];
};

const toInt = toNonNegIntOrNull;

/** エリア集計は「値なしの行」も 0 人として足す（店舗カードは null のまま扱う＝既存の差）。 */
function rowTotal(r: StoreCardRangeRow): number {
  return rowTotalOrNull(r) ?? 0;
}

function jstHourOf(ts: string): number | null {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  // en-CA: 「20時」のような接尾辞が付かず数字だけ得られる（ja-JP だと "20時" になり Number() が NaN）
  const hh = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    hourCycle: "h23",
  }).format(d);
  const n = Number(hh);
  return Number.isFinite(n) ? n : null;
}

function hmJst(ts: string | undefined): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : formatNowHmJst(d);
}

/**
 * 1店舗分: /api/range の行から、対象の夜（window）に入る実測だけを使って1行分のテキストを作る。
 * その夜に「人がいた」実測が1点も無ければ null（＝その店の行は出さない）。
 *
 * @param completed その夜が終わっているか（true なら「いま」を出さない）
 */
export function buildAreaStoreLiveLine(
  store: StoreMeta,
  rows: readonly StoreCardRangeRow[],
  window: { start: Date; end: Date },
  completed: boolean,
): AreaStoreLiveLine | null {
  const ordered = orderedRangeRows([...rows]).filter((r) => isWithinNight(r.ts, window));
  if (ordered.length === 0) return null;

  // 「人がいた」行が1つも無い夜（休業日・計測不能）は空箱を作らない
  const nonZero = ordered.filter((r) => rowTotal(r) > 0);
  if (nonZero.length === 0) return null;

  const percentBrand = isPercentCrowdBrand(store.brand);
  const percentMode = percentBrand && !!store.capacity;
  const capacity = store.capacity ?? 0;

  const describeCounts = (men: number, women: number, total: number): string | null => {
    if (total <= 0) return null;
    const ratio = `男${Math.round((men / total) * 100)}% / 女${Math.round((women / total) * 100)}%`;
    if (percentMode) {
      const overall = seatFullnessPercentOfTotal(total, capacity);
      if (overall === null) return null;
      const mp = seatFullnessPercent(men, capacity);
      const wp = seatFullnessPercent(women, capacity);
      return mp !== null && wp !== null
        ? `席の埋まり具合 約${overall}%（男性${mp}% / 女性${wp}%）`
        : `席の埋まり具合 約${overall}%`;
    }
    if (percentBrand) {
      // capacity 不明の相席屋: 人数を出せず % も計算できないので男女比のみ
      return `男女比 ${ratio}`;
    }
    return `男性${men}人 / 女性${women}人（${ratio}）`;
  };

  // いま（進行中の夜のみ・直近ティックに人がいるときだけ）
  const latest = ordered[ordered.length - 1];
  const latestTotal = rowTotal(latest);
  const nowText =
    !completed && latestTotal > 0
      ? describeCounts(toInt(latest.men) ?? 0, toInt(latest.women) ?? 0, latestTotal)
      : null;

  // その夜のピーク（実測の最大。同値なら先に到達した時刻）
  let peakRow = nonZero[0];
  for (const r of nonZero) if (rowTotal(r) > rowTotal(peakRow)) peakRow = r;
  const peakHm = hmJst(peakRow.ts);
  const peakDesc = describeCounts(
    toInt(peakRow.men) ?? 0,
    toInt(peakRow.women) ?? 0,
    rowTotal(peakRow),
  );
  const peakText = peakHm && peakDesc ? `${peakHm} に最多（${peakDesc}）` : null;

  // 時間帯別: 実測を「時」でまとめ、その時間帯の最大値を代表値にする（19→23→0→5 の夜順）
  const hourPoints: { hour: number; total: number }[] = [];
  for (const r of ordered) {
    if (!r.ts) continue;
    const h = jstHourOf(r.ts);
    if (h === null) continue;
    hourPoints.push({ hour: h, total: rowTotal(r) });
  }
  const buckets = rollUpByNightHour(hourPoints);
  let hourlyText: string | null = null;
  if (buckets.length >= MIN_HOURLY_BUCKETS) {
    const parts = buckets
      .map(({ hour: h, total: t }) => {
        if (percentMode) {
          const p = seatFullnessPercentOfTotal(t, capacity);
          return p === null ? null : `${h}時 約${p}%`;
        }
        if (percentBrand) return null;
        return `${h}時 ${t}人`;
      })
      .filter((x): x is string => x !== null);
    if (parts.length >= MIN_HOURLY_BUCKETS) hourlyText = parts.join(" / ");
  }

  const latestHm = hmJst(latest.ts);
  const updatedText = latestHm ? (completed ? `最終計測 ${latestHm}` : `${latestHm} 時点`) : null;

  return {
    slug: store.slug,
    storeName: buildStoreFullName(store),
    nowText,
    peakText,
    hourlyText,
    updatedText,
  };
}

/** 夜の基準日（19:00 側の JST 日付）を「8/18」の形にする */
function formatNightMd(baseDate: Date): string {
  return `${baseDate.getMonth() + 1}/${baseDate.getDate()}`;
}

/**
 * エリア全店分。`bySlug` は slug → /api/range の rows。
 * 1店も出せる実測が無ければ null（呼び出し側はセクションごと省く）。
 */
export function buildAreaLiveSummary(
  stores: readonly StoreMeta[],
  bySlug: Readonly<Record<string, readonly StoreCardRangeRow[] | undefined>>,
  now: Date,
): AreaLiveSummary | null {
  const baseDate = computeNightBaseDate(now);
  const window = computeNightWindowFromBaseDate(baseDate);
  const completed = isNightCompleted(baseDate, now);
  const nightLabel = completed ? `直近の営業夜（${formatNightMd(baseDate)}）` : "今夜";
  const lines: AreaStoreLiveLine[] = [];
  for (const store of stores) {
    const rows = bySlug[store.slug];
    if (!rows || rows.length === 0) continue;
    const line = buildAreaStoreLiveLine(store, rows, window, completed);
    if (line) lines.push(line);
  }
  return lines.length > 0 ? { nightLabel, completed, lines } : null;
}
