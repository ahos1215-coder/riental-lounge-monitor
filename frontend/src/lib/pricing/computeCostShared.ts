// frontend/src/lib/pricing/computeCostShared.ts
//
// 料金計算のブランド非依存部分（時刻変換・営業ウィンドウ・入退店の妥当性チェック）。
//
// 経緯: computeCost.ts（551行）の後半150行が相席屋専用だったため
// computeCostAisekiya.ts へ分離した際、双方が使う下回りをここへ置いた。
// こうすると computeCost → computeCostAisekiya → computeCostShared の一方向依存で済み、
// 循環 import（computeCost が再公開しつつ相席屋側が computeCost を import する形）を作らずに済む。
import type { DayType, PricingTableBase } from "@/data/pricing/types";

export type ChargeLine = {
  label: string;
  amount: number;
};

/** "HH:MM" を「開店日からの分」に変換。24時以降（翌日側）は 24:00〜59:59 の表記を想定。 */
export function timeToMinutes(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m) throw new Error(`Invalid time string: ${hhmm}`);
  const h = Number(m[1]);
  const min = Number(m[2]);
  return h * 60 + min;
}

/** 表示用に「分」を "HH:MM" へ戻す。30:00 は "06:00"、24:30 は "24:30" のまま表示する（翌日感を残す）。 */
export function minutesToTimeLabel(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  const displayH = h % 24;
  return `${displayH.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
}

/**
 * 指定した曜日タイプの営業ウィンドウ（分・openTime基準）を返す。
 * openTimeByDayType/closeTimeByDayType が店舗ごとに異なるため、店舗+曜日タイプ
 * ごとに動的に決まる。PricingTableBase のみに依存するためブランド非依存
 * （オリエンタル・相席屋どちらの PricingTable も渡せる）。
 */
export function windowMinutes(
  pricing: PricingTableBase,
  dayType: DayType,
): { minEntry: number; maxExit: number } {
  const minEntry = timeToMinutes(pricing.openTimeByDayType[dayType]);
  const maxExit = timeToMinutes(pricing.closeTimeByDayType[dayType]);
  return { minEntry, maxExit };
}

/**
 * "HH:MM" を、店舗の営業ウィンドウ内の「分」に正規化する。openTime（両曜日タイプの
 * うち早い方）より前の時刻（00:00〜openTime未満）は自動的に翌日側とみなす。
 */
export function normalizeStayMinutes(hhmm: string, openTime: string): number {
  const t = timeToMinutes(hhmm);
  const open = timeToMinutes(openTime);
  return t < open ? t + 24 * 60 : t;
}

export type ValidationResult = { ok: true } | { ok: false; reason: string };

/**
 * 入店・退店時刻の妥当性チェック（曜日タイプ別の営業時間内・entry<exit・実閉店時刻まで）。
 * PricingTableBase のみに依存するためブランド非依存（相席屋の自由計算にも使う）。
 */
export function validateStayWindow(
  pricing: PricingTableBase,
  dayType: DayType,
  entryMinutes: number,
  exitMinutes: number,
): ValidationResult {
  const { minEntry, maxExit } = windowMinutes(pricing, dayType);
  const openLabel = minutesToTimeLabel(minEntry);
  const closeLabel = minutesToTimeLabel(maxExit);

  if (entryMinutes < minEntry) {
    return { ok: false, reason: `入店時刻は${openLabel}以降にしてください。` };
  }
  if (entryMinutes >= maxExit) {
    return { ok: false, reason: `入店時刻は${closeLabel}（Close）より前にしてください。` };
  }
  if (exitMinutes <= entryMinutes) {
    return { ok: false, reason: "退店時刻は入店時刻より後にしてください。" };
  }
  if (exitMinutes > maxExit) {
    return { ok: false, reason: `退店時刻は${closeLabel}（Close）までにしてください。` };
  }
  return { ok: true };
}
