// frontend/src/lib/date/nightWindow.ts
//
// 日付・JST・夜窓（19:00-翌05:00 JST）に関する純粋関数だけを集めたモジュール。
// React import は一切含まない。
//
// 経緯: これらの関数はもともと frontend/src/app/hooks/storePreviewSnapshot.ts に
// 「系列構築」「ピーク/鮮度分析」「スナップショット組み立て」と同居していたが、
// 実体は app/hooks（クライアントフック層）に依存しない汎用の日付/JSTユーティリティ
// だったため、components からの参照が components → app/hooks という逆転依存を
// 生んでいた。ロジックを変更せず本モジュールへ機械的に移設する
// （storePreviewSnapshot.ts は re-export バレルとしてこれらを再公開する）。
import type { PreviewRangeMode } from "@/lib/forecast/types";
import { jstDateParts, jstHm } from "./jst";

export type NightWindowRange = {
  start: Date;
  end: Date;
};

export function formatYMD(date: Date): string {
  const y = date.getFullYear();
  const m = (date.getMonth() + 1).toString().padStart(2, "0");
  const d = date.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function parseYMD(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!m) return null;

  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);

  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return null;
  }

  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// The venues are in Japan and the night window is JST 19:00-05:00. Compute the base
// date in Asia/Tokyo regardless of the viewer's device timezone, otherwise a non-JST
// visitor filters/labels the wrong slice. JST is fixed +09:00 (no DST).
//
// 「19時境界」の規約はここだけ。00:00-05:59 を前夜とする -6h 規約（レポート/料金判定）
// とは別物なので混同しないこと（対比は lib/date/jst.ts のヘッダ参照）。
//
// baseDate carries the JST night-date via its Y/M/D; it is only read through
// getFullYear/getMonth/getDate for date arithmetic, never as an absolute instant.
export function computeNightBaseDate(now: Date): Date {
  const p = jstDateParts(now);
  const base = new Date(p.year, p.month - 1, p.day);
  if (p.hour < 19) {
    base.setDate(base.getDate() - 1);
  }
  return base;
}

export function computeNightWindowFromBaseDate(baseDate: Date): NightWindowRange {
  const startYmd = `${baseDate.getFullYear()}-${pad2(baseDate.getMonth() + 1)}-${pad2(baseDate.getDate())}`;
  const nextDay = new Date(baseDate);
  nextDay.setDate(nextDay.getDate() + 1);
  const endYmd = `${nextDay.getFullYear()}-${pad2(nextDay.getMonth() + 1)}-${pad2(nextDay.getDate())}`;
  // Absolute JST instants (+09:00) so isWithinNight's getTime() comparison is correct
  // for any viewer timezone.
  const start = new Date(`${startYmd}T19:00:00+09:00`);
  const end = new Date(`${endYmd}T05:00:00+09:00`);
  return { start, end };
}

export function computeSelectedNightBaseDate(
  mode: PreviewRangeMode,
  customDate: string,
  now: Date,
): Date {
  const todayBase = computeNightBaseDate(now);
  const selected = new Date(todayBase);

  if (mode === "yesterday") {
    selected.setDate(selected.getDate() - 1);
    return selected;
  }

  if (mode === "lastWeek") {
    selected.setDate(selected.getDate() - 7);
    return selected;
  }

  if (mode === "custom") {
    return parseYMD(customDate) ?? todayBase;
  }

  return todayBase;
}

export function isWithinNight(ts: string | undefined, window: NightWindowRange): boolean {
  if (!ts) return false;
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return false;
  const time = t.getTime();
  return time >= window.start.getTime() && time <= window.end.getTime();
}

/**
 * 夜の baseDate（19:00 側の JST 日付）を、スナップショットのストレージキーと同じ
 * YYYYMMDD 形式にする（scripts/snapshot_forecasts.py の `night_date` と一致させる）。
 * baseDate は getFullYear/getMonth/getDate だけで JST の Y/M/D を運ぶ値なので、
 * ここでもそれ以外（getTime 等）は参照しない。
 */
export function nightDateYYYYMMDD(baseDate: Date): string {
  const y = baseDate.getFullYear();
  const m = pad2(baseDate.getMonth() + 1);
  const d = pad2(baseDate.getDate());
  return `${y}${m}${d}`;
}

/**
 * 対象の夜（baseDate 19:00 始まり）が、`now` 時点で既に終わっている（窓の終わり
 * ＝ 翌日 05:00 JST を過ぎている）かどうか。
 * - 「今日」モードでも、05:00-19:00 の間（次の夜がまだ始まっていない）はここで
 *   true になる＝直近に終わった夜の予測スナップショットを見せる対象になる。
 * - 「昨日」「先週」は baseDate が常に過去なので、実質的に常に true。
 * - 「カスタム」で未来日を選んだ場合は false（まだ配信すらされていない）。
 */
export function isNightCompleted(baseDate: Date, now: Date): boolean {
  const window = computeNightWindowFromBaseDate(baseDate);
  return now.getTime() >= window.end.getTime();
}

/** JST の「HH:MM」。実体は lib/date/jst の jstHm（import 互換のため名前を維持）。 */
export function formatNowHmJst(date: Date): string {
  return jstHm(date);
}
