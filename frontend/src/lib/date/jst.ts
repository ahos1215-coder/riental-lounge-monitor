// frontend/src/lib/date/jst.ts
//
// JST（Asia/Tokyo）の日付部品・整形の単一ソース。
//
// 店舗は全て日本にあり、営業は夜をまたぐ。閲覧者の端末タイムゾーンに関係なく
// 「日本時間の何日の何時か」で判定・表示する必要があるため、JST 変換はすべて
// このモジュールを経由させる（同じ Intl オプションの手書きコピーを各所に増やさない）。
//
// このファイルには「夜の日付」の2規約が両方あるので、必ず対比して読むこと:
//   1. 夜セッション日付（-6h 規約 / NIGHT_SESSION_SHIFT_HOURS）
//      00:00-05:59 JST は「前夜」。Python 側 oriental/ml/night_type.py の
//      NIGHT_SESSION_SHIFT_HOURS=6 と同じ規約で、レポートの target_date や
//      料金判定（深夜は前日の夜営業の続き）に使う。→ nightSessionAnchorUtcMs
//   2. 表示夜窓の基準日（19時境界）
//      19:00-翌05:00 を1つの「夜」として描画するためのもので、hour < 19 なら前日。
//      こちらは lib/date/nightWindow.ts の computeNightBaseDate 側にある。

export const JST_TIME_ZONE = "Asia/Tokyo";

/**
 * 夜セッションの日付境界（-6h シフト規約）。00:00-05:59 JST は「前夜」として扱う。
 * Python 側の単一ソースは oriental/ml/night_type.py の NIGHT_SESSION_SHIFT_HOURS=6。
 */
export const NIGHT_SESSION_SHIFT_HOURS = 6;

const DAY_MS = 24 * 60 * 60 * 1000;

export type JstDateParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
};

const PARTS_FORMAT = new Intl.DateTimeFormat("en-CA", {
  timeZone: JST_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  hourCycle: "h23",
});

const YMD_FORMAT = new Intl.DateTimeFormat("en-CA", {
  timeZone: JST_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const HM_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  timeZone: JST_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * JST の年/月/日/時を数値で取り出す。
 * Intl が想定外に部品を返さなかった場合は 0 として扱う寛容版（判定を止めない）。
 * 「値が取れなかったこと」を呼び出し側で区別したいときは jstDatePartsOrNull を使う。
 */
export function jstDateParts(d: Date): JstDateParts {
  const parts = PARTS_FORMAT.formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
  };
}

/**
 * jstDateParts の厳格版。部品が欠けている / 数値にならない場合は null を返し、
 * 呼び出し側が「判定不能」として従来どおりのフォールバックへ倒せるようにする。
 */
export function jstDatePartsOrNull(d: Date): JstDateParts | null {
  const parts = PARTS_FORMAT.formatToParts(d);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? NaN);
  const year = get("year");
  const month = get("month");
  const day = get("day");
  const hour = get("hour");
  if ([year, month, day, hour].some((v) => !Number.isFinite(v))) return null;
  return { year, month, day, hour };
}

/** JST の「YYYY-MM-DD」。引数省略時は現在時刻。 */
export function jstYmd(d: Date = new Date()): string {
  return YMD_FORMAT.format(d);
}

/** JST の「HH:MM」（24時間表記・2桁ゼロ埋め）。 */
export function jstHm(d: Date): string {
  return HM_FORMAT.format(d);
}

/**
 * 夜セッション（-6h 規約）の基準日を UTC ミリ秒で返す。
 * JST の Y/M/D をそのまま Date.UTC に載せた値なので、絶対時刻ではなく
 * 「日付を運ぶための UTC 深夜」として getUTC*() 経由でだけ読むこと。
 * 例: 土曜 02:00 JST → 金曜（前日の夜営業の続き）。
 */
export function nightSessionAnchorUtcMs(now: Date): number {
  const p = jstDateParts(now);
  const base = Date.UTC(p.year, p.month - 1, p.day);
  return p.hour < NIGHT_SESSION_SHIFT_HOURS ? base - DAY_MS : base;
}

/** UTC ミリ秒（日付を運ぶ値）を「YYYY-MM-DD」にする。 */
export function utcMsToYmd(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** 夜セッション基準日の翌日（祝前日判定などで使う）。 */
export function nextDayUtcMs(ms: number): number {
  return ms + DAY_MS;
}
