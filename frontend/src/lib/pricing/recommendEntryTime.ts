// frontend/src/lib/pricing/recommendEntryTime.ts
//
// 「今夜の入店の目安」ロジック（純粋関数・APIコールなし）。
//
// useStorePreviewData が既に取得しているタイムライン系列（実測+予測、約15分刻み）を
// 入力として、男性視点で「何時ごろ入店すると良さそうか」の目安時刻を算出する。
// 判定はすべて予測データの数値に基づき、UI側は「目安」として提示する（断定しない）。
//
// アルゴリズム上のメタ知見（オーナー要望に基づく除外ルール）:
//   - 開店直後（19:30より前）は候補から除外する。開店直後に来店する女性は
//     無料の飲食のみが目的である可能性があり、シグナルとして信頼しにくいため。
//   - 24:00以降は候補から除外する。終電後で帰宅制約が強く、料金も最高価格帯
//     （10分¥770/週末¥800）に入り、多くの店で人数も下り坂になるため。

import type { DayType, PricingTable } from "@/data/pricing/nagasaki";
import { minutesToTimeLabel, timeToMinutes, unitPriceAtMinute } from "./computeCost";

/** useStorePreviewData の TimeSeriesPoint と構造互換の最小型（labelは "HH:MM"） */
export type ForecastSlotLike = {
  label: string;
  menActual?: number | null;
  womenActual?: number | null;
  menForecast?: number | null;
  womenForecast?: number | null;
};

export type RecommendOptions = {
  /** 料金の安いバンドを優先するタイブレークに使う曜日タイプ（既定: weekday） */
  dayType?: DayType;
};

export type EntryRecommendation = {
  /** スコア最大のスロット時刻（openTime基準の分） */
  entryMinutes: number;
  /** 表示用に30分単位へ切り下げた時刻（分） */
  entryDisplayMinutes: number;
  /** 表示用ラベル（"23:30" など） */
  entryDisplayLabel: string;
  /** 評価ウィンドウの終端（entry + 90分） */
  windowEndMinutes: number;
  windowEndLabel: string;
  womenAvg: number;
  menAvg: number;
  /** ウィンドウ内の女性比（%・四捨五入） */
  ratioPct: number;
  /** 直近30分で女性が増加傾向か */
  rising: boolean;
  /** 夜全体が静かな予測（nightPeakWomen < QUIET_NIGHT_PEAK_WOMEN） */
  quietNight: boolean;
  /** 根拠として表示する短いデータ文（推薦の言い回しはしない） */
  reasons: string[];
};

// ---- 調整用定数（名前付き。変更時はコメントの根拠も更新すること） ----

/** 候補の下限 19:30。開店直後の女性はただ飯目的の可能性（オーナーのメタ知見）→除外 */
const CANDIDATE_START_MIN = 19 * 60 + 30;
/** 候補の上限 24:00（含まない）。終電後・最高価格帯・多くの店で下り坂→除外 */
const CANDIDATE_END_MIN = 24 * 60;
/** 入店後の評価ウィンドウ（典型的な滞在の見込み時間） */
const WINDOW_MIN = 90;
/** 増加傾向（momentum）を見る幅 */
const MOMENTUM_WINDOW_MIN = 30;
/** 閑散フィルタの絶対下限（女性平均がこれ未満なら候補から外す） */
const CROWD_FLOOR_ABS = 3;
/** 閑散フィルタの相対下限（夜のピーク女性数に対する比率） */
const CROWD_FLOOR_PEAK_RATIO = 0.25;
/** 女性比のスケール中心。0.5以上=「女性がやや多い」 */
const RATIO_MIDPOINT = 0.5;
/** ratio_factor の上限。比率が絶対数を支配しすぎないよう軽く飽和させる */
const RATIO_CAP = 1.15;
/** 女性が増加中の候補へのボーナス（同数なら「増えている最中」の入店が有利） */
const MOMENTUM_BONUS = 1.05;
/** 20:30より前のソフトペナルティ。宵の口の女性数はシグナルとして弱い（ただ飯根拠の延長） */
const EARLY_CAUTION_BEFORE_MIN = 20 * 60 + 30;
const EARLY_CAUTION_FACTOR = 0.8;
/** タイブレーク対象（ベストスコアに対する比率） */
const TIEBREAK_RATIO = 0.95;
/** 夜のピーク女性数がこれ未満なら「今夜は全体的に静か」の注記を付ける */
const QUIET_NIGHT_PEAK_WOMEN = 4;

type ParsedSlot = {
  minute: number;
  women: number;
  men: number;
};

/** "HH:MM" ラベルを openTime(18:00) 基準の分に正規化（朝方は翌日側 24:00〜） */
function slotMinuteFromLabel(label: string, openMinutes: number): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(label.trim());
  if (!m) return null;
  const t = Number(m[1]) * 60 + Number(m[2]);
  return t < openMinutes ? t + 24 * 60 : t;
}

/** 実測を優先し、なければ予測を使う（過去=実測、未来=予測で夜の連続カーブになる） */
function slotValue(actual: number | null | undefined, forecast: number | null | undefined): number | null {
  if (typeof actual === "number" && Number.isFinite(actual)) return Math.max(0, actual);
  if (typeof forecast === "number" && Number.isFinite(forecast)) return Math.max(0, forecast);
  return null;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** t に最も近いスロットの女性数（nearest-slot） */
function womenNear(slots: ParsedSlot[], t: number): number | null {
  let best: ParsedSlot | null = null;
  let bestDist = Infinity;
  for (const s of slots) {
    const d = Math.abs(s.minute - t);
    if (d < bestDist) {
      bestDist = d;
      best = s;
    }
  }
  return best ? best.women : null;
}

/**
 * タイムライン系列から「今夜の入店の目安」を算出する。
 * 予測データが無い場合は null を返す（UI側で「予測が出たら表示」の案内を出す）。
 */
export function recommendEntryTime(
  series: ForecastSlotLike[],
  pricing: PricingTable,
  opts: RecommendOptions = {},
): EntryRecommendation | null {
  const dayType: DayType = opts.dayType ?? "weekday";
  const openMinutes = timeToMinutes(pricing.openTime);

  // 予測が1点も無い夜（実測のみ/データなし）は目安を出さない
  const hasAnyForecast = series.some(
    (p) =>
      (typeof p.womenForecast === "number" && Number.isFinite(p.womenForecast)) ||
      (typeof p.menForecast === "number" && Number.isFinite(p.menForecast)),
  );
  if (!hasAnyForecast) return null;

  const slots: ParsedSlot[] = [];
  for (const p of series) {
    const minute = slotMinuteFromLabel(p.label, openMinutes);
    if (minute == null) continue;
    const women = slotValue(p.womenActual, p.womenForecast);
    const men = slotValue(p.menActual, p.menForecast);
    if (women == null && men == null) continue;
    slots.push({ minute, women: women ?? 0, men: men ?? 0 });
  }
  if (slots.length === 0) return null;
  slots.sort((a, b) => a.minute - b.minute);

  const nightPeakWomen = Math.max(...slots.map((s) => s.women));
  const crowdFloor = Math.max(CROWD_FLOOR_ABS, CROWD_FLOOR_PEAK_RATIO * nightPeakWomen);

  type Candidate = {
    minute: number;
    score: number;
    womenAvg: number;
    menAvg: number;
    ratio: number;
    rising: boolean;
    womenMin: number;
    womenMax: number;
  };

  const candidates: Candidate[] = [];
  for (const slot of slots) {
    const t = slot.minute;
    if (t < CANDIDATE_START_MIN || t >= CANDIDATE_END_MIN) continue;

    const windowSlots = slots.filter((s) => s.minute >= t && s.minute < t + WINDOW_MIN);
    if (windowSlots.length === 0) continue;

    const womenAvg = windowSlots.reduce((sum, s) => sum + s.women, 0) / windowSlots.length;
    const menAvg = windowSlots.reduce((sum, s) => sum + s.men, 0) / windowSlots.length;
    const denom = womenAvg + menAvg;
    const ratio = denom > 0 ? womenAvg / denom : 0;

    const wNow = womenNear(slots, t);
    const wLater = womenNear(slots, t + MOMENTUM_WINDOW_MIN);
    const rising = wNow != null && wLater != null && wLater > wNow;

    let score: number;
    if (womenAvg < crowdFloor) {
      score = 0; // 閑散フィルタ
    } else {
      const ratioFactor = clamp(ratio / RATIO_MIDPOINT, 0, RATIO_CAP);
      const momentumBonus = rising ? MOMENTUM_BONUS : 1.0;
      const earlyCaution = t < EARLY_CAUTION_BEFORE_MIN ? EARLY_CAUTION_FACTOR : 1.0;
      score = womenAvg * ratioFactor * momentumBonus * earlyCaution;
    }

    candidates.push({
      minute: t,
      score,
      womenAvg,
      menAvg,
      ratio,
      rising,
      womenMin: Math.min(...windowSlots.map((s) => s.women)),
      womenMax: Math.max(...windowSlots.map((s) => s.women)),
    });
  }
  if (candidates.length === 0) return null;

  const bestScore = Math.max(...candidates.map((c) => c.score));
  const quietNight = nightPeakWomen < QUIET_NIGHT_PEAK_WOMEN;

  let picked: Candidate;
  if (bestScore <= 0) {
    // 全候補が閑散フィルタで0点 → それでも「最も女性が多い」時間帯を目安として返す
    picked = [...candidates].sort(
      (a, b) => b.womenAvg - a.womenAvg || a.minute - b.minute,
    )[0];
  } else {
    // ベストの95%以内はタイブレーク: 料金バンドが安い（=早い）候補を優先
    const contenders = candidates.filter((c) => c.score >= bestScore * TIEBREAK_RATIO);
    contenders.sort((a, b) => {
      const pa = unitPriceAtMinute(pricing, dayType, a.minute) ?? Number.MAX_SAFE_INTEGER;
      const pb = unitPriceAtMinute(pricing, dayType, b.minute) ?? Number.MAX_SAFE_INTEGER;
      if (pa !== pb) return pa - pb;
      return a.minute - b.minute;
    });
    picked = contenders[0];
  }

  const entryDisplayMinutes = Math.floor(picked.minute / 30) * 30;
  const entryDisplayLabel = minutesToTimeLabel(entryDisplayMinutes);
  const windowEndMinutes = picked.minute + WINDOW_MIN;
  const windowEndLabel = minutesToTimeLabel(windowEndMinutes);

  const wMinR = Math.round(picked.womenMin);
  const wMaxR = Math.round(picked.womenMax);
  const womenRangeText = wMinR === wMaxR ? `約${wMaxR}人` : `${wMinR}〜${wMaxR}人`;
  const ratioPct = Math.round(picked.ratio * 100);

  const reasons: string[] = [
    `${minutesToTimeLabel(picked.minute)}〜${windowEndLabel} は女性 ${womenRangeText}・女性比 ${ratioPct}% の予測`,
  ];
  if (picked.rising) {
    reasons.push("女性は増加中の予測");
  }
  if (quietNight) {
    reasons.push("今夜は全体的に静かな予測です");
  }

  return {
    entryMinutes: picked.minute,
    entryDisplayMinutes,
    entryDisplayLabel,
    windowEndMinutes,
    windowEndLabel,
    womenAvg: picked.womenAvg,
    menAvg: picked.menAvg,
    ratioPct,
    rising: picked.rising,
    quietNight,
    reasons,
  };
}
