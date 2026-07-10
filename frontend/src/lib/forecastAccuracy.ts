/**
 * 予測精度カード（ForecastAccuracyCard）の数値整形ロジック。
 * 「実測（本番）を正直に見せる」ための土台となる純粋関数群。
 * 表示コンポーネントから切り離してテスト可能にしている。
 */

export type LiveWindowInput = {
  mae_30d: number | null | undefined;
  mae_7d: number | null | undefined;
  nights_count: number | null | undefined;
};

export type NightsWindow = {
  /** 実際に集計できた夜数（バックエンドの実測値をそのまま使う。捏造しない）。 */
  nights: number;
  /** UI表示用ラベル。例: "直近7夜" */
  label: string;
  /**
   * 30夜分のデータが揃って mae_30d が非nullになったかどうか。
   * n<30 の間はバックエンドが mae_30d=null を返す設計のため、
   * これが true になるまでは「集計中」の注記を出す。
   */
  matured: boolean;
};

/**
 * サイト全体の実測ウィンドウ情報を導出する。
 * mae_30d と mae_7d のどちらも無い、または nights_count が0以下なら
 * 実測データがまだ無いとみなし null を返す（フォールバック側の表示に譲る）。
 */
export function resolveNightsWindow(live: LiveWindowInput | null | undefined): NightsWindow | null {
  if (!live) return null;
  const nights = live.nights_count;
  if (nights == null || nights <= 0) return null;
  const hasAnyMae = live.mae_30d != null || live.mae_7d != null;
  if (!hasAnyMae) return null;
  return {
    nights,
    label: `直近${nights}夜`,
    matured: live.mae_30d != null,
  };
}

export type StoreLiveComparison = {
  mae: number;
  baseline: number;
  /** ML の誤差がベースラインより大きい（＝現状負けている）かどうか。 */
  worse: boolean;
};

/** 精度バッジのランク。表示ラベル/色はカード側でこのキーから引く。 */
export type AccuracyGrade = "high" | "standard" | "reference";

/**
 * 相対誤差（= live_mae / 想定夜間来客数）のしきい値。
 * 「絶対人数」ではなく「店舗規模に対する相対的な当たり具合」でランク付けするための境界。
 * 実測データ (2026-07-09, 42店) で調整: 30%未満=規模比で明確に良い / 50%未満=標準 /
 * それ以上=小規模で相対誤差が大きい店。
 */
export const GRADE_HIGH_MAX_RELATIVE = 0.30;
export const GRADE_STANDARD_MAX_RELATIVE = 0.50;

export type AccuracyGradeInput = {
  /** 実測(本番)スコアがあるか。無ければ holdout フォールバック＝参考値。 */
  hasLive: boolean;
  /** 店舗規模で正規化した相対誤差 = live_mae / 想定夜間来客数。無ければ null。 */
  relativeMae?: number | null;
  /** ナイーブ基準(先週同時刻)に勝っているか。false は規模に関わらず参考値どまり。 */
  beatsBaseline?: boolean | null;
};

/**
 * 予測精度バッジの判定を「絶対人数」ではなく「相対性能」で行う純関数。
 *
 * 判定順:
 * 1. 実測が無い（学習時 holdout フォールバック）→ 参考値。
 * 2. 実測はあるがナイーブ基準に負けている（beatsBaseline===false）→ 相対誤差や
 *    絶対 MAE に関わらず参考値どまり（小さい MAE でも "高精度/標準" を出さない）。
 *    これが「基準より悪い店が 標準/高精度 になる」逆転を直接止める。
 * 3. それ以外は店舗規模で正規化した相対誤差 relativeMae でランク付け。
 * 4. 相対誤差が取れない（スナップショット未取得）が基準には勝っている場合は、
 *    精緻なランク付けはできないので中位の「標準」に留める。
 */
export function resolveAccuracyGrade(input: AccuracyGradeInput): AccuracyGrade {
  if (!input.hasLive) return "reference";
  if (input.beatsBaseline === false) return "reference";
  const rel = input.relativeMae;
  if (rel != null && Number.isFinite(rel)) {
    if (rel < GRADE_HIGH_MAX_RELATIVE) return "high";
    if (rel < GRADE_STANDARD_MAX_RELATIVE) return "standard";
    return "reference";
  }
  if (input.beatsBaseline === true) return "standard";
  return "reference";
}

/**
 * この店舗自身の実測MAEと、同店舗の単純ベースライン（先週同時刻など）を比較する。
 * サイト全体の集計値ではなく、店舗ごとの実数値を使うことで
 * 「全体では互角でもこの店は大きく負けている（またはその逆）」を隠さない。
 */
export function resolveStoreComparison(
  liveMae: number | null | undefined,
  liveBaselineMae: number | null | undefined,
): StoreLiveComparison | null {
  if (liveMae == null || liveBaselineMae == null) return null;
  if (!Number.isFinite(liveMae) || !Number.isFinite(liveBaselineMae)) return null;
  return { mae: liveMae, baseline: liveBaselineMae, worse: liveMae > liveBaselineMae };
}
