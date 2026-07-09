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
