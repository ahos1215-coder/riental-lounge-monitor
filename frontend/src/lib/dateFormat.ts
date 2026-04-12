/**
 * JST 日時フォーマットの共通ユーティリティ。
 *
 * レポートページ / API ルート / チャートコンポーネントで重複していた
 * フォーマット関数を 1 箇所に集約。
 */

const JST = "Asia/Tokyo";
const DOW_JA = ["日", "月", "火", "水", "木", "金", "土"] as const;

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

/**
 * ISO タイムスタンプ → 「3/31」形式 (日付のみ)。
 * チャート X 軸のティックラベル用。
 */
export function formatAxisDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: JST,
      month: "numeric",
      day: "numeric",
    }).format(d);
  } catch {
    return "";
  }
}

/**
 * ISO タイムスタンプ → 「4/3 20:35(木)」形式。
 * チャートのツールチップ用 (formatWindowTime と同等だがチャート専用)。
 */
export function formatTooltipTime(iso: string): string {
  return formatWindowTime(iso);
}
