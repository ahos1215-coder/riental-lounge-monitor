// frontend/src/lib/pricing/computeCost.ts
//
// 料金シミュレーターの計算ロジック（純粋関数・APIコールなし）。
//
// 課金モデルの前提:
//   公式サイトは「10分毎課金」とだけ記載しており、明示的な端数処理ルールの記載は無い。
//   本シミュレーターは一般的な「10分毎自動延長」の考え方に基づき、
//     - 滞在時間を10分単位に切り上げる（例: 25分滞在 = 3ユニット）
//     - 各ユニットの単価は、そのユニットの「開始時刻」が属する時間帯バンドで決まる
//   という前提で計算する。実際の課金タイミング（入店時刻基準の10分区切りか、
//   00分/10分単位の壁時計基準か）は公式サイトに明記が無いため、入店時刻を起点に
//   10分区切りで計算している（UIにも前提として注記する）。

import type { DayType, PricingTable, PricingBand } from "@/data/pricing/nagasaki";

/** "HH:MM" を「開店日からの分」に変換。24時以降（翌日側）は 24:00〜29:59 の表記を想定。 */
function timeToMinutes(hhmm: string): number {
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

export type UnitBreakdownRow = {
  band: PricingBand;
  minutes: number;
  unitPrice: number;
  units: number;
  subtotal: number;
};

export type ChargeLine = {
  label: string;
  amount: number;
};

export type PriceBoundary = {
  /** "HH:MM" 表記（24時以降は 24:00〜29:59 のまま） */
  atLabel: string;
  atMinutes: number;
  oldPrice: number;
  newPrice: number;
};

export type CostResult = {
  total: number;
  unitsBreakdown: UnitBreakdownRow[];
  charges: ChargeLine[];
  /** entry〜exit の間に単価が変わる境界（値上がりの事実のみを示す。演出的な言い回しはしない） */
  boundaries: PriceBoundary[];
};

export type ComputeCostOptions = {
  appCheckin: boolean;
  solo: boolean;
};

const MIN_ENTRY_MINUTES = timeToMinutes("18:00");
const MAX_ENTRY_MINUTES = timeToMinutes("29:50"); // 05:50 (翌日側表記)
const MAX_EXIT_MINUTES = timeToMinutes("30:00"); // 06:00 (翌日側表記)

/**
 * 入店/退店の "HH:MM" を、営業ウィンドウ（18:00開店〜翌06:00閉店）内の「分」に正規化する。
 * 00:00〜05:59 のような「深夜〜早朝」表記は自動的に翌日側（24:00〜29:59）とみなす。
 */
export function normalizeStayMinutes(hhmm: string, openTime: string): number {
  const t = timeToMinutes(hhmm);
  const open = timeToMinutes(openTime);
  // 0:00-17:59 の時刻は「開店日の翌日」を意味するとみなし +24h する
  return t < open ? t + 24 * 60 : t;
}

function findBandForMinute(bands: PricingBand[], minute: number): PricingBand | null {
  for (const band of bands) {
    const start = timeToMinutes(band.start);
    const end = timeToMinutes(band.end);
    if (minute >= start && minute < end) return band;
  }
  return null;
}

/** 指定した「分」（openTime基準に正規化済み）が属するバンドの10分単価。営業時間外は null。 */
export function unitPriceAtMinute(
  pricing: PricingTable,
  dayType: DayType,
  minute: number,
): number | null {
  const band = findBandForMinute(pricing.bands, minute);
  return band ? band[dayType] : null;
}

export type ValidationResult = { ok: true } | { ok: false; reason: string };

/** 入店・退店時刻の妥当性チェック（営業時間内・entry<exit・上限06:00など） */
export function validateStayWindow(
  pricing: PricingTable,
  entryMinutes: number,
  exitMinutes: number,
): ValidationResult {
  if (entryMinutes < MIN_ENTRY_MINUTES) {
    return { ok: false, reason: "入店時刻は18:00以降にしてください。" };
  }
  if (entryMinutes > MAX_ENTRY_MINUTES) {
    return { ok: false, reason: "入店時刻は翌5:50までにしてください。" };
  }
  if (exitMinutes <= entryMinutes) {
    return { ok: false, reason: "退店時刻は入店時刻より後にしてください。" };
  }
  if (exitMinutes > MAX_EXIT_MINUTES) {
    return { ok: false, reason: "退店時刻は翌6:00（Close）までにしてください。" };
  }
  return { ok: true };
}

/**
 * 男性の滞在料金を計算する。
 * - 10分単位に切り上げ、各ユニットは「ユニット開始時刻」が属するバンドの単価で計算する。
 * - entry/exitMinutes は openTime(18:00)を基準に正規化済みの「分」であること
 *   （normalizeStayMinutes で変換してから渡す）。
 */
export function computeStayCost(
  pricing: PricingTable,
  dayType: DayType,
  entryMinutes: number,
  exitMinutes: number,
  opts: ComputeCostOptions,
): CostResult {
  const validation = validateStayWindow(pricing, entryMinutes, exitMinutes);
  if (!validation.ok) {
    throw new Error(validation.reason);
  }

  const totalMinutesRaw = exitMinutes - entryMinutes;
  const unitMinutes = pricing.unitMinutes;
  const totalUnits = Math.ceil(totalMinutesRaw / unitMinutes);

  // バンドごとに「ユニット数・単価」を集計する
  const perBandUnits = new Map<PricingBand, number>();
  const boundaries: PriceBoundary[] = [];
  let prevBand: PricingBand | null = null;

  for (let i = 0; i < totalUnits; i += 1) {
    const unitStart = entryMinutes + i * unitMinutes;
    const band = findBandForMinute(pricing.bands, unitStart);
    if (!band) {
      throw new Error(`No pricing band found for minute ${unitStart} (${minutesToTimeLabel(unitStart)})`);
    }
    perBandUnits.set(band, (perBandUnits.get(band) ?? 0) + 1);

    if (prevBand && prevBand !== band) {
      const oldPrice = prevBand[dayType];
      const newPrice = band[dayType];
      if (newPrice !== oldPrice) {
        boundaries.push({
          atLabel: minutesToTimeLabel(unitStart),
          atMinutes: unitStart,
          oldPrice,
          newPrice,
        });
      }
    }
    prevBand = band;
  }

  const unitsBreakdown: UnitBreakdownRow[] = pricing.bands
    .map((band) => {
      const units = perBandUnits.get(band) ?? 0;
      if (units === 0) return null;
      const unitPrice = band[dayType];
      return {
        band,
        minutes: units * unitMinutes,
        unitPrice,
        units,
        subtotal: units * unitPrice,
      };
    })
    .filter((row): row is UnitBreakdownRow => row !== null);

  const stayTotal = unitsBreakdown.reduce((sum, row) => sum + row.subtotal, 0);

  const charges: ChargeLine[] = [];
  if (opts.appCheckin) {
    charges.push({ label: "チャージ（アプリチェックインで無料）", amount: 0 });
  } else {
    charges.push({ label: "チャージ", amount: pricing.charges.entry });
  }
  if (opts.solo) {
    charges.push({ label: "シングルチャージ（お一人様利用）", amount: pricing.charges.single });
  }

  const chargesTotal = charges.reduce((sum, c) => sum + c.amount, 0);

  return {
    total: stayTotal + chargesTotal,
    unitsBreakdown,
    charges,
    boundaries,
  };
}

/**
 * 「ピーク◯時間前に入店し、◯時間滞在／クローズまで滞在した場合」のプラン用に、
 * entry からの滞在時間バリエーション（1h/2h/3h/クローズまで）をまとめて計算する。
 */
export type StayPlanOption = {
  label: string;
  exitLabel: string;
  exitMinutes: number;
  result: CostResult;
};

export function computeStayPlans(
  pricing: PricingTable,
  dayType: DayType,
  entryMinutes: number,
  opts: ComputeCostOptions,
): StayPlanOption[] {
  const closeMinutes = timeToMinutes(pricing.closeTime);
  const durations: { label: string; minutes: number | null }[] = [
    { label: "1時間", minutes: 60 },
    { label: "2時間", minutes: 120 },
    { label: "3時間", minutes: 180 },
    { label: "クローズまで", minutes: null },
  ];

  const plans: StayPlanOption[] = [];
  for (const d of durations) {
    const exitMinutes = d.minutes == null ? closeMinutes : Math.min(entryMinutes + d.minutes, closeMinutes);
    if (exitMinutes <= entryMinutes) continue;
    try {
      const result = computeStayCost(pricing, dayType, entryMinutes, exitMinutes, opts);
      plans.push({
        label: d.label,
        exitLabel: minutesToTimeLabel(exitMinutes),
        exitMinutes,
        result,
      });
    } catch {
      // 営業時間外などで計算不能な場合はそのプランをスキップ
    }
  }
  return plans;
}

export { timeToMinutes };
