// frontend/src/lib/forecast/types.ts
//
// 店舗プレビュー（実測＋予測）で使う「型」だけを集めたモジュール。値も React も持たない。
//
// 経緯: これらの型は app/hooks/storePreviewSnapshot.ts で定義されていたが、
// lib 側（seriesAnalysis / ssrSummary / nightWindow）や components が
// app/hooks を型 import する形になり、lib → app/hooks の逆転依存・
// nightWindow ↔ storePreviewSnapshot の型循環 import を生んでいた。
// 型の実体をここ（lib）へ移し、app/hooks/storePreviewSnapshot.ts と
// app/hooks/useStorePreviewData.ts は `export type { ... } from` で再公開する
// （既存の import 元は無改修のまま動く）。
import type { BrandId } from "@/app/config/stores";

export type PreviewRangeMode = "today" | "yesterday" | "lastWeek" | "custom";

export type TimeSeriesPoint = {
  ts?: string;
  label: string;
  menActual: number | null;
  womenActual: number | null;
  menForecast: number | null;
  womenForecast: number | null;
};

/**
 * 予測データの取得状態。一過性の Supabase Storage 障害などで `/api/forecast_today`
 * が空配列を返した場合、フックが自動再試行する。UI 側はこの値を見て
 * 「予測を再取得しています」等のヒントを出せる。
 *
 * - `idle`: まだ予測リクエストを行っていない（today モード以外）
 * - `ok`: 予測データを取得できた
 * - `retrying`: 予測が空だったため自動再試行中
 * - `unavailable`: 自動再試行の上限に達してもデータが取れなかった
 * - `insufficient_history`: 店舗の履歴データがまだ無く、そもそも予測できない
 *   （バックエンドが `insufficient_history:true` を返した場合。再試行しても状況は
 *   変わらないため、retrying ループには入らずすぐにこの状態を出す）
 */
export type ForecastStatus = "idle" | "ok" | "retrying" | "unavailable" | "insufficient_history";

export type StoreSnapshot = {
  slug: string;
  name: string;
  area: string;
  /** ブランド（相席屋は人数非公開＝%表示に切替）。 */
  brand: BrandId;
  /** 相席屋の席数（%逆算用）。他ブランドは null。 */
  capacity: number | null;
  level: string;
  nowTotal: number;
  nowMen: number;
  nowWomen: number;
  peakTimeLabel: string;
  peakTotal: number;
  peakMen: number | null;
  peakWomen: number | null;
  recommendation: string;
  forecastUpdatedLabel: string;
  series: TimeSeriesPoint[];
  hasData: boolean;
  forecastStatus: ForecastStatus;
  /**
   * 最新の実測データ点の ts（ISO文字列）。「◯分前更新」の鮮度表示に使う。
   * 実測データが1件も無い場合は null（表示側は「データなし」扱い）。
   */
  latestActualTs: string | null;
  /**
   * ピーク（最も混雑した系列点）の ts（ISO文字列・絶対時刻）。null は不明。
   * 「ピークまで あと約…」チップが、ピークを既に過ぎた後も"これから盛り上がる"方向へ
   * 誤誘導しないよう、描画時に `new Date()` と比較して「ピークは過ぎたか」を判定するために使う。
   */
  peakTs: string | null;
  /**
   * 表示対象の夜が既に終わっている（回顧的表示）かどうか。
   * - 「昨日」「先週」「過去日カスタム」は常に true。
   * - 「今日」モードでも、夜が既に終わった（05:00-19:00 の間など）場合は true。
   * 完了済みの夜では「ピークまで あと約…」や「ピークは過ぎました（進行中の含意）」を
   * 出さない（答え合わせ表示なので現在進行の文言は誤解を招く）。
   */
  completedNight: boolean;
};

export type RangePoint = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

export type ForecastPoint = {
  ts?: string;
  // 履歴データ不足の店舗ではバックエンドが null を返す（0.0 との区別のため）。
  men_pred?: number | null;
  women_pred?: number | null;
  total_pred?: number | null;
};
