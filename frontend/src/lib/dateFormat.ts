/**
 * JST 日時フォーマットの共通ユーティリティ。
 *
 * レポートページ / API ルート / チャートコンポーネントで重複していた
 * フォーマット関数を 1 箇所に集約。
 */

import {
  JST_TIME_ZONE,
  jstDatePartsOrNull,
  nightSessionAnchorUtcMs,
  utcMsToYmd,
} from "@/lib/date/jst";

const JST = JST_TIME_ZONE;
const DOW_JA = ["日", "月", "火", "水", "木", "金", "土"] as const;

/**
 * 「今の夜セッションの日付」(JST, YYYY-MM-DD)。00:00-05:59 は前夜扱い（-6h シフト）。
 *
 * 日次レポートの `target_date` は生成時刻（18:00 / 21:30 JST）の JST 日付＝その夜の日付なので、
 * この値と突き合わせれば「その記事が今夜のものか、前回の夜のものか」を判定できる。
 * 判定できないとき（Intl が想定外の値を返す等）は空文字を返し、呼び出し側で
 * 「判定不能＝従来どおり」にフォールバックできるようにする。
 */
export function jstNightSessionDate(now: Date = new Date()): string {
  if (Number.isNaN(now.getTime())) return "";
  try {
    // -6h 規約の条件式は lib/date/jst の nightSessionAnchorUtcMs が単一ソース。
    // ここは「部品が取れなかったら判定不能（空文字）」という呼び出し側の作法だけを持つ。
    if (!jstDatePartsOrNull(now)) return "";
    return utcMsToYmd(nightSessionAnchorUtcMs(now));
  } catch {
    return "";
  }
}

/**
 * 「2026-08-19」→「8/19」。日付文字列（YYYY-MM-DD）専用の軽量フォーマッタで、
 * タイムゾーン変換は一切しない（target_date は既に JST の日付のため）。
 * 形式が違えば空文字を返す。
 */
export function formatJstMonthDay(ymd: string | undefined | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((ymd ?? "").trim());
  if (!m) return "";
  return `${Number(m[2])}/${Number(m[3])}`;
}

/**
 * ISO タイムスタンプ → 「4月11日 22:33」形式。
 * レポートヘッダーの「○○更新」表示用。
 */
export function formatJstTimestamp(iso: string | undefined | null): string {
  const raw = iso?.trim();
  if (!raw) return "-";
  try {
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: JST,
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(raw));
  } catch {
    return raw.slice(0, 16).replace("T", " ");
  }
}

/**
 * ISO タイムスタンプ → 「2026/04/11 22:33」形式。
 * API レスポンスの updatedLabel 用。
 */
export function formatJstLabel(iso: string | undefined | null): string {
  const raw = iso?.trim();
  if (!raw) return "-";
  try {
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: JST,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(raw));
  } catch {
    return raw.slice(0, 16).replace("T", " ");
  }
}

/**
 * ISO タイムスタンプ → 「4/3 20:35(木)」形式。
 * Weekly Report の Good Window 表示用。
 */
export function formatWindowTime(iso: string | undefined | null): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    const jst = new Date(d.toLocaleString("en-US", { timeZone: JST }));
    const dayOfWeek = DOW_JA[jst.getDay()];
    return (
      new Intl.DateTimeFormat("ja-JP", {
        timeZone: JST,
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(d) + `(${dayOfWeek})`
    );
  } catch {
    return (iso ?? "").slice(0, 16).replace("T", " ");
  }
}
