// frontend/src/lib/pricing/computeCostAisekiya.ts
//
// 相席屋（AisekiyaPricingTable）専用の料金計算。computeCost.ts から分離した
// （UI 側も OrientalCostSimulatorCard / AisekiyaCostSimulatorCard に分かれているため、
//  ブランドごとの課金規則が対応する UI と同じ粒度で分かれる）。
// computeCost.ts が末尾で `export * from "./computeCostAisekiya"` して再公開するので、
// 既存の import パス（@/lib/pricing/computeCost）は無改修で動く。
import type { AisekiyaPricingTable, DayType } from "@/data/pricing/types";
import {
  minutesToTimeLabel,
  validateStayWindow,
  windowMinutes,
  type ChargeLine,
} from "./computeCostShared";

// ============================================================================
// 相席屋（AisekiyaPricingTable）向けの計算ロジック
// ============================================================================
//
// オリエンタルとの違い:
//   - 時間帯バンドが無く、相席時はフラット10分単価（曜日タイプ別）が基本。
//     ただし「22:00以降は10%加算」というチェーン共通ルールがあるため、実際は
//     22:00を境に2段階の単価になる（オリエンタルの時間帯バンドと同様に、金額を
//     正しく反映するのが目的。以前は加算を注記のみで済ませ本体金額に反映して
//     いなかったが、22:00をまたぐ滞在で金額が過小表示になる＝ユーザーが実際に
//     払う額より安く見える不整合があったため、加算を計算に組み込むよう修正した）。
//   - 相席していない時間は無料（¥0）。オーナー承認済みの簡素化方針により、
//     見出しの1数値は「滞在時間すべてが相席だった場合」の金額（=オリエンタルの
//     maxTotal と同じ考え方）を表示する。実際の会計は¥0〜この金額の間に収まる。
//   - シングルチャージ（お一人様追加課金）の概念が無い（AisekiyaCharges に
//     single フィールドが無い）ため、ComputeCostOptions の solo は使わない。
//
// ■ 22:00以降の10%加算の計算モデル（6店舗全店共通・生HTMLで再確認済み）
//   各10分ユニットの「開始時刻」が22:00以降（openTime基準の分で 22*60=1320 以降。
//   翌0:00=1440・翌1:00=1500なども当然1320以降なので深夜も対象）なら、そのユニット
//   の単価を josekiRate[dayType] × 1.1 とし、円未満は四捨五入する
//   （¥650×1.1=¥715、¥750×1.1=¥825）。22:00より前に開始するユニットは
//   josekiRate[dayType] のまま。
//   注意: 加算後の¥715/¥825は税込参考値(josekiRateTaxIncluded)と数値が一致するが、
//   これは偶然であり意味は全く別物（片方は消費税、片方は深夜割増）。混同しない
//   ために josekiRateTaxIncluded は再利用せず、× 1.1 を独立に計算している。
//   全アイセキヤ店舗が開店18:00以前（=22:00より前に開店）のため、22:00は必ず
//   openTime以降＝normalizeStayMinutesで翌日側へシフトされることは無く、
//   固定で 1320 分として扱える。

/** 22:00以降10%加算の開始時刻（openTime基準の分）。全アイセキヤ店舗は22時前に開店。 */
export const AISEKIYA_LATE_NIGHT_FROM_MINUTES = 22 * 60;
/** 22:00以降の割増率（10%加算＝×1.1）。 */
export const AISEKIYA_LATE_NIGHT_MULTIPLIER = 1.1;

/** 相席屋の指定曜日タイプ・指定深夜フラグにおける相席10分単価（円・四捨五入）。 */
export function aisekiyaUnitPrice(baseRate: number, isLateNight: boolean): number {
  return isLateNight ? Math.round(baseRate * AISEKIYA_LATE_NIGHT_MULTIPLIER) : baseRate;
}

/** そのユニット開始分が22:00以降（=深夜割増対象）か。 */
function isAisekiyaLateNightMinute(unitStartMinute: number): boolean {
  return unitStartMinute >= AISEKIYA_LATE_NIGHT_FROM_MINUTES;
}

export type AisekiyaCostResult = {
  /** 滞在時間すべてが相席だった場合の合計（相席ぶん小計 + チャージ）。22:00以降は10%加算済み。 */
  total: number;
  /** 相席10分単価（22:00より前・通常単価。参考表示用） */
  unitPrice: number;
  /** 22:00以降の相席10分単価（通常単価×1.1・四捨五入。参考表示用） */
  lateNightUnitPrice: number;
  /** 合計ユニット数（10分単位・切り上げ） */
  totalUnits: number;
  /** 22:00より前に開始したユニット数（通常単価） */
  normalUnits: number;
  /** 22:00以降に開始したユニット数（10%加算単価） */
  lateNightUnits: number;
  /** 通常単価ぶんの小計（normalUnits × unitPrice） */
  normalSubtotal: number;
  /** 深夜加算ぶんの小計（lateNightUnits × lateNightUnitPrice） */
  lateNightSubtotal: number;
  /** 相席ぶんの小計（チャージ抜き。normalSubtotal + lateNightSubtotal） */
  staySubtotal: number;
  charges: ChargeLine[];
};

type ComputeAisekiyaCostOptions = {
  /** アプリパスポート等でチャージが無料になっている場合 true */
  appCheckin: boolean;
};

/**
 * 相席屋の男性滞在料金を計算する（見出しの1数値=ずっと相席だった場合の金額）。
 * - 10分単位に切り上げ、各ユニットの「開始時刻」が22:00以降なら10%加算単価、
 *   それ以外は通常単価 josekiRate[dayType] を適用して合算する。
 * - entry/exitMinutes は openTime を基準に正規化済みの「分」であること
 *   （normalizeStayMinutes で変換してから渡す。オリエンタルと共通の関数）。
 * - 営業時間外・entry>=exit は validateStayWindow が先に弾く（オリエンタルと共通）。
 */
export function computeAisekiyaStayCost(
  pricing: AisekiyaPricingTable,
  dayType: DayType,
  entryMinutes: number,
  exitMinutes: number,
  opts: ComputeAisekiyaCostOptions,
): AisekiyaCostResult {
  const validation = validateStayWindow(pricing, dayType, entryMinutes, exitMinutes);
  if (!validation.ok) {
    throw new Error(validation.reason);
  }

  const totalMinutesRaw = exitMinutes - entryMinutes;
  const unitMinutes = pricing.unitMinutes;
  const totalUnits = Math.ceil(totalMinutesRaw / unitMinutes);
  const baseRate = pricing.josekiRate[dayType];
  const lateNightUnitPrice = aisekiyaUnitPrice(baseRate, true);

  // 各ユニットの開始時刻で通常/深夜を判定して合算する（オリエンタルの
  // computeStayCost がバンド単価を積み上げるのと同じ考え方）。
  let normalUnits = 0;
  let lateNightUnits = 0;
  for (let i = 0; i < totalUnits; i += 1) {
    const unitStart = entryMinutes + i * unitMinutes;
    if (isAisekiyaLateNightMinute(unitStart)) {
      lateNightUnits += 1;
    } else {
      normalUnits += 1;
    }
  }

  const normalSubtotal = normalUnits * baseRate;
  const lateNightSubtotal = lateNightUnits * lateNightUnitPrice;
  const staySubtotal = normalSubtotal + lateNightSubtotal;

  const charges: ChargeLine[] = [];
  if (opts.appCheckin) {
    charges.push({ label: "チャージ（アプリチェックインで無料）", amount: 0 });
  } else {
    charges.push({ label: "チャージ", amount: pricing.charges.entry });
  }
  const chargesTotal = charges.reduce((sum, c) => sum + c.amount, 0);

  return {
    total: staySubtotal + chargesTotal,
    unitPrice: baseRate,
    lateNightUnitPrice,
    totalUnits,
    normalUnits,
    lateNightUnits,
    normalSubtotal,
    lateNightSubtotal,
    staySubtotal,
    charges,
  };
}

type AisekiyaStayPlanOption = {
  label: string;
  exitLabel: string;
  exitMinutes: number;
  result: AisekiyaCostResult;
};

/**
 * オリエンタルの computeStayPlans と同じ考え方（1h/2h/3h/クローズまでの
 * バリエーションをまとめて計算する）を相席屋向けに提供する。
 */
export function computeAisekiyaStayPlans(
  pricing: AisekiyaPricingTable,
  dayType: DayType,
  entryMinutes: number,
  opts: ComputeAisekiyaCostOptions,
): AisekiyaStayPlanOption[] {
  const { maxExit } = windowMinutes(pricing, dayType);
  const durations: { label: string; minutes: number | null }[] = [
    { label: "1時間", minutes: 60 },
    { label: "2時間", minutes: 120 },
    { label: "3時間", minutes: 180 },
    { label: "クローズまで", minutes: null },
  ];

  const plans: AisekiyaStayPlanOption[] = [];
  for (const d of durations) {
    const exitMinutes = d.minutes == null ? maxExit : Math.min(entryMinutes + d.minutes, maxExit);
    if (exitMinutes <= entryMinutes) continue;
    try {
      const result = computeAisekiyaStayCost(pricing, dayType, entryMinutes, exitMinutes, opts);
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

