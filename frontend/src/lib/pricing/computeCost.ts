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
  PricingTableBase,
} from "@/data/pricing/types";

/** "HH:MM" を「開店日からの分」に変換。24時以降（翌日側）は 24:00〜59:59 の表記を想定。 */
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
 * 指定した曜日タイプの営業ウィンドウ（分・openTime基準）を返す。
 * openTimeByDayType/closeTimeByDayType が店舗ごとに異なるため、店舗+曜日タイプ
 * ごとに動的に決まる。PricingTableBase のみに依存するためブランド非依存
 * （オリエンタル・相席屋どちらの PricingTable も渡せる）。
 */
function windowMinutes(pricing: PricingTableBase, dayType: DayType): { minEntry: number; maxExit: number } {
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

export { timeToMinutes };
