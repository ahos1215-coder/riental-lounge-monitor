// frontend/src/lib/pricing/jpHolidays.ts
//
// 日本の国民の祝日の静的リスト（2026年・2027年）と、料金シミュレーター用の
// 平日/週末（金・土・祝前日）自動判定。
//
// 出典: 内閣府「国民の祝日について」 https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html
// カバー範囲: 2026-01-01 〜 2027-12-31。2028年以降を使う時期になったらここに追記する。
// 注意: 春分の日・秋分の日は前年2月の官報公示で正式確定する（2027年分は天文計算に
// 基づく予定日で、変更される可能性はごく低いが零ではない）。
//
// 年末年始・GW・お盆などの「特別期間の週末料金」は店舗ごとの運用で期間が明示されて
// いないため、自動判定には含めない（UI側で「特別期間は手動で週末を選択」と案内する）。

import type { DayType } from "@/data/pricing/nagasaki";

export const JP_HOLIDAYS_2026_2027: ReadonlySet<string> = new Set<string>([
  // ---- 2026年 ----
  "2026-01-01", // 元日
  "2026-01-12", // 成人の日
  "2026-02-11", // 建国記念の日
  "2026-02-23", // 天皇誕生日
  "2026-03-20", // 春分の日
  "2026-04-29", // 昭和の日
  "2026-05-03", // 憲法記念日（日曜）
  "2026-05-04", // みどりの日
  "2026-05-05", // こどもの日
  "2026-05-06", // 振替休日（5/3が日曜のため）
  "2026-07-20", // 海の日
  "2026-08-11", // 山の日
  "2026-09-21", // 敬老の日
  "2026-09-22", // 国民の休日（敬老の日と秋分の日に挟まれた平日）
  "2026-09-23", // 秋分の日
  "2026-10-12", // スポーツの日
  "2026-11-03", // 文化の日
  "2026-11-23", // 勤労感謝の日
  // ---- 2027年 ----
  "2027-01-01", // 元日
  "2027-01-11", // 成人の日
  "2027-02-11", // 建国記念の日
  "2027-02-23", // 天皇誕生日
  "2027-03-21", // 春分の日（日曜・予定日）
  "2027-03-22", // 振替休日
  "2027-04-29", // 昭和の日
  "2027-05-03", // 憲法記念日
  "2027-05-04", // みどりの日
  "2027-05-05", // こどもの日
  "2027-07-19", // 海の日
  "2027-08-11", // 山の日
  "2027-09-20", // 敬老の日
  "2027-09-23", // 秋分の日（予定日）
  "2027-10-11", // スポーツの日
  "2027-11-03", // 文化の日
  "2027-11-23", // 勤労感謝の日
]);

export function isJpHoliday(ymd: string): boolean {
  return JP_HOLIDAYS_2026_2027.has(ymd);
}

export type DayTypeDetection = {
  dayType: DayType;
  /** 判定に使った基準日（JST・夜営業の基準日）"YYYY-MM-DD" */
  anchorYmd: string;
  /** 基準日の曜日ラベル（"火" など） */
  dowLabel: string;
  /** 判定理由（"金曜" | "土曜" | "祝前日" | "平日"） */
  reason: "金曜" | "土曜" | "祝前日" | "平日";
};

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"] as const;

function jstParts(d: Date): { year: number; month: number; day: number; hour: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
  };
}

function formatUtcYmd(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = (d.getUTCMonth() + 1).toString().padStart(2, "0");
  const day = d.getUTCDate().toString().padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 「今日は平日料金か週末料金か」をJST基準で自動判定する。
 *
 * 判定ルール（公式サイトの注記に準拠）:
 *   金曜・土曜・祝前日（翌日が祝日）→ 週末料金
 *   それ以外 → 平日料金
 *
 * 基準日の考え方: 店舗の営業は 18:00〜翌06:00 の夜またぎなので、JSTで朝6時前の
 * 時刻は「前日の夜営業の続き」とみなし、前日を基準日として判定する
 * （例: 土曜 午前2時 = 金曜の夜 → 金曜として週末料金）。
 *
 * 年末年始・GW・お盆などの特別期間は含まない（期間が公式に明示されていないため、
 * UI側で手動切り替えを案内する）。
 */
export function detectDayTypeJst(now: Date): DayTypeDetection {
  const p = jstParts(now);
  let anchorMs = Date.UTC(p.year, p.month - 1, p.day);
  if (p.hour < 6) {
    anchorMs -= DAY_MS; // 深夜〜早朝は前日の夜営業として扱う
  }
  const anchor = new Date(anchorMs);
  const dow = anchor.getUTCDay();
  const anchorYmd = formatUtcYmd(anchorMs);
  const dowLabel = DOW_LABELS[dow];

  if (dow === 5) {
    return { dayType: "weekend", anchorYmd, dowLabel, reason: "金曜" };
  }
  if (dow === 6) {
    return { dayType: "weekend", anchorYmd, dowLabel, reason: "土曜" };
  }
  const nextYmd = formatUtcYmd(anchorMs + DAY_MS);
  if (isJpHoliday(nextYmd)) {
    return { dayType: "weekend", anchorYmd, dowLabel, reason: "祝前日" };
  }
  return { dayType: "weekday", anchorYmd, dowLabel, reason: "平日" };
}
