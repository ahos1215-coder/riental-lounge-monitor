// frontend/src/lib/pricing/computeCost.ts
//
// 料金シミュレーターの計算ロジック（純粋関数・APIコールなし）。全36店舗の
// PricingTable（openH/closeHのばらつき・バンド数のばらつき・曜日タイプ別の
// 営業時間・null バンドを含む）に対応する。
//
// 課金モデルの前提:
//   公式の10分単価は「その時間に相席しているかどうか」で切り替わる
//   （トップページ #price: 単独10分 220円〜 / 相席10分 440円〜。詳細は
//   data/pricing/raw.ts の先頭コメント参照）。相席していた時間の割合は
//   事前に分からないため、本シミュレーターは両端を計算する:
//     - maxTotal = 滞在の全時間が相席だった場合（時間帯バンド単価）＝予算安全側の上限
//     - minTotal = 相席が一度も無かった場合（全ユニット soloRate）＝下限
//   実際の会計はこの間に収まる。UI表示は現状 maxTotal のみを見せる方針
//   （オーナー要望、CostSimulatorCard.tsx 参照）だが、エンジンは両方を返す。
//
//   公式サイトは「10分毎課金」とだけ記載しており、明示的な端数処理ルールの記載は無い。
//   本シミュレーターは一般的な「10分毎自動延長」の考え方に基づき、
//     - 滞在時間を10分単位に切り上げる（例: 25分滞在 = 3ユニット）
//     - 各ユニットの単価は、そのユニットの「開始時刻」が属する時間帯バンドで決まる
//   という前提で計算する。実際の課金タイミング（入店時刻基準の10分区切りか、
//   00分/10分単位の壁時計基準か）は公式サイトに明記が無いため、入店時刻を起点に
//   10分区切りで計算している（UIにも前提として注記する）。
//
// ■ 最終バンドの「Close」延長ルール（全36店舗共通の一般化ポイント）
//   多くの店舗は平日と週末で実際の閉店時刻が異なるが（例: 小倉は平日02:00・
//   週末05:00）、価格表は「24時〜Close」のような単一バンドを両曜日タイプで
//   共有しており、専用の延長バンド行を持たない店舗が大半（2026-07-08 の
//   全36店舗クロスチェックで確認）。この場合「Close」は各曜日の実際の閉店を
//   指す動的な意味と解釈し、最終バンド（その曜日タイプで null でない最後の
//   バンド）の単価を、そのバンド自身の end を超えて実際の閉店時刻
//   （closeTimeByDayType[dayType]）まで延長して適用する。
//   渋谷店のように専用の延長バンド（weekday:null の「6時〜Close」）を明示的に
//   持つ店舗は、そのバンド自身の値をそのまま使うので、この延長ロジックは
//   実質的に発火しない（延長対象がそもそも無いため）。

import type {
  AisekiyaPricingTable,
  DayType,
  OrientalPricingTable,
  PricingBand,
} from "@/data/pricing/types";
import {
  minutesToTimeLabel,
  timeToMinutes,
  validateStayWindow,
  windowMinutes,
  type ChargeLine,
} from "./computeCostShared";

// 下回り（時刻変換・営業ウィンドウ・妥当性チェック）の実体は computeCostShared.ts。
// 既存の import 元（UI・recommendEntryTime・テスト）が壊れないよう、ここから再公開する。
export {
  minutesToTimeLabel,
  normalizeStayMinutes,
  timeToMinutes,
  validateStayWindow,
} from "./computeCostShared";
export type { ChargeLine, ValidationResult } from "./computeCostShared";

export type UnitBreakdownRow = {
  band: PricingBand;
  minutes: number;
  unitPrice: number;
  units: number;
  subtotal: number;
};

export type PriceBoundary = {
  /** "HH:MM" 表記（24時以降は 24:00〜59:59 のまま） */
  atLabel: string;
  atMinutes: number;
  oldPrice: number;
  newPrice: number;
};

export type CostResult = {
  /** 上限: 滞在の全時間が相席だった場合（時間帯バンド単価 + チャージ類） */
  maxTotal: number;
  /** 下限: 相席が一度も無かった場合（全ユニット soloRate + チャージ類） */
  minTotal: number;
  /** 相席ケース（上限側）のバンド別内訳 */
  unitsBreakdown: UnitBreakdownRow[];
  charges: ChargeLine[];
  /** entry〜exit の間に相席単価が変わる境界（値上がりの事実のみを示す。演出的な言い回しはしない） */
  boundaries: PriceBoundary[];
  /** 合計ユニット数（10分単位・切り上げ） */
  totalUnits: number;
};

export type ComputeCostOptions = {
  appCheckin: boolean;
  solo: boolean;
};

/**
 * 指定した曜日タイプにおける「実際に販売されている最後のバンド」を返す
 * （= その曜日タイプで weekday/weekend が null でない最後のバンド）。
 * 渋谷店のような weekday:null バンドがある店舗では、平日の最終バンドは
 * その1つ手前になる。
 */
function lastActiveBand(bands: PricingBand[], dayType: DayType): PricingBand | null {
  for (let i = bands.length - 1; i >= 0; i -= 1) {
    if (bands[i][dayType] !== null) return bands[i];
  }
  return null;
}

/**
 * 指定した「分」が属するバンドを探す。見つからず、かつ実際の閉店時刻
 * （closeTimeByDayType[dayType]）の範囲内であれば、最終バンド（lastActiveBand）を
 * 「Close」延長として返す（コメント冒頭「最終バンドのClose延長ルール」参照）。
 * 完全に範囲外（開店前・実閉店後）は null。
 */
function findBandForMinute(
  pricing: OrientalPricingTable,
  dayType: DayType,
  minute: number,
): PricingBand | null {
  for (const band of pricing.bands) {
    if (band[dayType] === null) continue; // この曜日タイプでは販売されていないバンドはスキップ
    const start = timeToMinutes(band.start);
    const end = timeToMinutes(band.end);
    if (minute >= start && minute < end) return band;
  }

  // どのバンドにも一致しなかった場合、実際の閉店時刻までは最終バンドの単価を延長する
  const { maxExit } = windowMinutes(pricing, dayType);
  const last = lastActiveBand(pricing.bands, dayType);
  if (last) {
    const lastEnd = timeToMinutes(last.end);
    if (minute >= lastEnd && minute < maxExit) return last;
  }

  return null;
}

/**
 * 指定した「分」（openTime基準に正規化済み）における10分単価。営業時間外は null。
 * オリエンタル（時間帯バンド制）・相席屋（フラット単価制）どちらの PricingTable
 * も受け取れる（recommendEntryTime.ts のタイブレーク用途がブランド非依存で
 * 動くようにするため）。相席屋は時間帯によらずフラットなので、営業時間内なら
 * 常に josekiRate[dayType] を返す（= 相席屋のタイブレークは実質no-opになる。
 * オリエンタルのように「安いバンドを優先する」余地がそもそも無いため正しい挙動）。
 */
export function unitPriceAtMinute(
  pricing: OrientalPricingTable | AisekiyaPricingTable,
  dayType: DayType,
  minute: number,
): number | null {
  if (pricing.model === "aisekiya") {
    const { minEntry, maxExit } = windowMinutes(pricing, dayType);
    if (minute < minEntry || minute >= maxExit) return null;
    return pricing.josekiRate[dayType];
  }
  const band = findBandForMinute(pricing, dayType, minute);
  if (!band) return null;
  return band[dayType]; // findBandForMinute が null バンドを除外済みなので number のはず
}

/**
 * 男性の滞在料金を計算する（上限=ずっと相席 / 下限=相席なし の両方）。
 * - 10分単位に切り上げ、上限側は各ユニットの「開始時刻」が属するバンドの単価、
 *   下限側は全ユニット soloRate[dayType] で計算する。
 * - entry/exitMinutes は openTime を基準に正規化済みの「分」であること
 *   （normalizeStayMinutes で変換してから渡す）。
 * - null バンド（その曜日タイプでは販売されていない時間帯）に滞在が入り込んだ
 *   場合はエラーを投げる（¥0やNaNへのフォールバックは行わない。通常は
 *   validateStayWindow が曜日タイプ別の実閉店時刻で先に弾くため到達しないはず）。
 */
export function computeStayCost(
  pricing: OrientalPricingTable,
  dayType: DayType,
  entryMinutes: number,
  exitMinutes: number,
  opts: ComputeCostOptions,
): CostResult {
  const validation = validateStayWindow(pricing, dayType, entryMinutes, exitMinutes);
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
    const band = findBandForMinute(pricing, dayType, unitStart);
    if (!band) {
      throw new Error(
        `No pricing band found for minute ${unitStart} (${minutesToTimeLabel(unitStart)}, dayType=${dayType})`,
      );
    }
    const price = band[dayType];
    if (price === null) {
      // findBandForMinute が null バンドを除外しているため通常到達しないが、
      // ¥0/NaNへの暗黙フォールバックを防ぐための明示ガード
      throw new Error(
        `Band "${band.label}" has no ${dayType} price at minute ${unitStart} (${minutesToTimeLabel(unitStart)})`,
      );
    }
    perBandUnits.set(band, (perBandUnits.get(band) ?? 0) + 1);

    if (prevBand && prevBand !== band) {
      const oldPrice = prevBand[dayType];
      if (oldPrice !== null && price !== oldPrice) {
        boundaries.push({
          atLabel: minutesToTimeLabel(unitStart),
          atMinutes: unitStart,
          oldPrice,
          newPrice: price,
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
      if (unitPrice === null) return null; // ガード（理論上到達しない）
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

  // 下限: 相席が一度も無かった場合（全ユニットが soloRate[dayType]）
  const soloStayTotal = totalUnits * pricing.soloRate[dayType];

  return {
    maxTotal: stayTotal + chargesTotal,
    minTotal: soloStayTotal + chargesTotal,
    unitsBreakdown,
    charges,
    boundaries,
    totalUnits,
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
  pricing: OrientalPricingTable,
  dayType: DayType,
  entryMinutes: number,
  opts: ComputeCostOptions,
): StayPlanOption[] {
  const { maxExit } = windowMinutes(pricing, dayType);
  const durations: { label: string; minutes: number | null }[] = [
    { label: "1時間", minutes: 60 },
    { label: "2時間", minutes: 120 },
    { label: "3時間", minutes: 180 },
    { label: "クローズまで", minutes: null },
  ];

  const plans: StayPlanOption[] = [];
  for (const d of durations) {
    const exitMinutes = d.minutes == null ? maxExit : Math.min(entryMinutes + d.minutes, maxExit);
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

// 相席屋の計算エンジンは computeCostAisekiya.ts に分離した（import パス互換のため再公開）。
export * from "./computeCostAisekiya";
