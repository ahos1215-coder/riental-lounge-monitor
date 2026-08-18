// frontend/src/lib/area/areaLiveSummary.ts
//
// エリアハブページ（/area/[area]）に「各店のいまの状況（実測）」をサーバー側HTMLの
// テキストとして出すための純粋関数。
//
// 背景（SEO Phase3-D）: エリアページは静的文言中心のテンプレで、単独店舗エリア9件は
// 互いに地名しか違わない「ほぼ同一ページ」になっていた（薄いページ量産のリスク）。
// ここで各店の実測値（直近の人数/男女比 or 席の埋まり具合%・時間帯別の推移・最終計測時刻）を
// テキスト化して載せることで、エリアごとに内容が異なる・利用者にも意味のあるページにする。
//
// データ源は /api/range_multi（一覧ページと同じ limit=48・per-store キャッシュを共有するため
// バックエンドへの追加負荷はほぼ無い）。取得できなければ呼び出し側がブロックごと省く。
//
// 厳守事項（lib/store/ssrSummary.ts と同じ）:
//  - 実データのみ。無い値は出さない（0人・--:-- 等の「空箱」を作らない）
//  - 相席屋（isPercentCrowdBrand）は在店人数を公開していないため、人数は一切出さず % のみ
//  - 時刻は JST 絶対時刻（「◯分前」は ISR で嘘になるため使わない）
import {
  buildStoreFullName,
  isPercentCrowdBrand,
  seatFullnessPercent,
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

/** 時間帯別サマリーを出すのに必要な最小の時間数（1点だけでは「推移」にならない） */
const MIN_HOURLY_BUCKETS = 2;

export type AreaStoreLiveLine = {
  slug: string;
  /** 「オリエンタルラウンジ 長崎」など */
  storeName: string;
  /** 「男性12人 / 女性9人（男57% / 女43%）」または「席の埋まり具合 約35%（男性30% / 女性40%）」 */
  nowText: string;
  /** 「20時 18人 / 21時 25人 / 22時 31人」。2時間分未満なら null */
  hourlyText: string | null;
  /** 「23:45 時点」。ts が読めなければ null */
  updatedText: string | null;
};

export type AreaLiveSummary = {
  /** 「今夜」（進行中の夜）or「直近の営業夜」（05:00〜19:00 の間） */
  nightLabel: string;
  lines: AreaStoreLiveLine[];
};

function toInt(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return Math.max(0, Math.round(v));
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.round(n));
  }
  return null;
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

/**
 * 1店舗分: /api/range_multi の行から、対象の夜（window）に入る実測だけを使って1行分のテキストを作る。
 * その夜の実測が1点も無ければ null（＝その店の行は出さない）。
 */
export function buildAreaStoreLiveLine(
  store: StoreMeta,
  rows: readonly StoreCardRangeRow[],
  window: { start: Date; end: Date },
): AreaStoreLiveLine | null {
  const ordered = orderedRangeRows([...rows]).filter((r) => isWithinNight(r.ts, window));
  if (ordered.length === 0) return null;

  const latest = ordered[ordered.length - 1];
  const men = toInt(latest.men) ?? 0;
  const women = toInt(latest.women) ?? 0;
  const total = toInt(latest.total) ?? men + women;
  if (total <= 0) return null;

  const percentBrand = isPercentCrowdBrand(store.brand);
  const percentMode = percentBrand && !!store.capacity;
  const capacity = store.capacity ?? 0;
  const ratio = `男${Math.round((men / total) * 100)}% / 女${Math.round((women / total) * 100)}%`;

  let nowText: string;
  if (percentMode) {
    const overall = seatFullnessPercent(total, capacity * 2);
    if (overall === null) return null;
    const mp = seatFullnessPercent(men, capacity);
    const wp = seatFullnessPercent(women, capacity);
    nowText =
      mp !== null && wp !== null
        ? `席の埋まり具合 約${overall}%（男性${mp}% / 女性${wp}%）`
        : `席の埋まり具合 約${overall}%`;
  } else if (percentBrand) {
    // capacity 不明の相席屋: 人数を出せず % も計算できないので男女比のみ
    nowText = `男女比 ${ratio}`;
  } else {
    nowText = `男性${men}人 / 女性${women}人（${ratio}）`;
  }

  // 時間帯別: 実測を「時」でまとめ、その時間帯の最大値を代表値にする（19→23→0→5 の夜順）
  const byHour = new Map<number, number>();
  for (const r of ordered) {
    if (!r.ts) continue;
    const h = jstHourOf(r.ts);
    if (h === null) continue;
    const t = toInt(r.total) ?? (toInt(r.men) ?? 0) + (toInt(r.women) ?? 0);
    if (t <= 0) continue;
    const prev = byHour.get(h);
    if (prev === undefined || t > prev) byHour.set(h, t);
  }
  const nightOrder = (h: number) => (h >= 19 ? h : h + 24);
  const buckets = [...byHour.entries()].sort((a, b) => nightOrder(a[0]) - nightOrder(b[0]));
  let hourlyText: string | null = null;
  if (buckets.length >= MIN_HOURLY_BUCKETS) {
    const parts = buckets
      .map(([h, t]) => {
        if (percentMode) {
          const p = seatFullnessPercent(t, capacity * 2);
          return p === null ? null : `${h}時 約${p}%`;
        }
        if (percentBrand) return null;
        return `${h}時 ${t}人`;
      })
      .filter((x): x is string => x !== null);
    if (parts.length >= MIN_HOURLY_BUCKETS) hourlyText = parts.join(" / ");
  }

  let updatedText: string | null = null;
  if (latest.ts) {
    const d = new Date(latest.ts);
    if (!Number.isNaN(d.getTime())) updatedText = `${formatNowHmJst(d)} 時点`;
  }

  return {
    slug: store.slug,
    storeName: buildStoreFullName(store),
    nowText,
    hourlyText,
    updatedText,
  };
}

/**
 * エリア全店分。`bySlug` は /api/range_multi の by_slug（slug → rows）。
 * 1店も出せる実測が無ければ null（呼び出し側はセクションごと省く）。
 */
export function buildAreaLiveSummary(
  stores: readonly StoreMeta[],
  bySlug: Readonly<Record<string, readonly StoreCardRangeRow[] | undefined>>,
  now: Date,
): AreaLiveSummary | null {
  const baseDate = computeNightBaseDate(now);
  const window = computeNightWindowFromBaseDate(baseDate);
  const nightLabel = isNightCompleted(baseDate, now) ? "直近の営業夜" : "今夜";
  const lines: AreaStoreLiveLine[] = [];
  for (const store of stores) {
    const rows = bySlug[store.slug];
    if (!rows || rows.length === 0) continue;
    const line = buildAreaStoreLiveLine(store, rows, window);
    if (line) lines.push(line);
  }
  return lines.length > 0 ? { nightLabel, lines } : null;
}
