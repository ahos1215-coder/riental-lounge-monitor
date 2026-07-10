// frontend/src/app/hooks/storePreviewSnapshot.ts
//
// useStorePreviewData（クライアントフック）と store/[id]/page.tsx（サーバーコンポーネント）の
// 両方から使う「型・純粋関数」だけを集めたモジュール。React import は一切含まない。
//
// 経緯: これらの純粋関数はもともと useStorePreviewData.ts に同居していたが、"use client" 前提の
// フック（useState/useEffect/useRef を使用）と同じファイルにあると、Server Component
// （store/[id]/page.tsx）がこのファイルを import した際に Next/Turbopack のモジュール境界解析で
// ビルドエラーになる（"You're importing a component that needs `useEffect`..." 等）。
// そのためロジックを重複させず、フレームワーク非依存の純粋関数だけをこの独立ファイルに切り出した。
//
// 2026-07 リファクタ: 日付/JST/夜窓の純粋関数は frontend/src/lib/date/nightWindow.ts へ、
// 系列構築・ピーク/鮮度分析の純粋関数は frontend/src/lib/forecast/seriesAnalysis.ts へ
// 機械的に移設した（components からの参照が components → app/hooks という逆転依存に
// なっていたのを解消するため）。このファイルはスナップショット組み立て用の型/定数/
// 純粋関数の実体を引き続き持ちつつ、移設先を re-export するバレルを兼ねる
// （既存の import 元を壊さないため）。
import {
  buildStoreFullName,
  type StoreMeta,
  type BrandId,
} from "../config/stores";

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

// NightWindow は frontend/src/lib/date/nightWindow.ts の NightWindowRange へ移設した。
export type { NightWindowRange } from "@/lib/date/nightWindow";

// 予測 API が空応答だった場合の自動再試行設定。
// 一過性の Supabase Storage 接続リセットや ML モデルプリロード待ちを想定し、
// 段階的に間隔を広げて最大 3 回まで再試行する。
// server-side snapshot（initialSnapshot）でグラフは既に初回描画できるため、
// クライアント側の再試行は最大待ち時間を 65s → 24s に短縮して体感を早める。
export const FORECAST_RETRY_DELAYS_MS: readonly number[] = [4_000, 8_000, 12_000];
export const FORECAST_MAX_RETRIES = FORECAST_RETRY_DELAYS_MS.length;

export const FORECAST_REFRESH_MS = 15 * 60 * 1000;

// initialSnapshot（サーバー seed）を消費した直後の最初のバックグラウンド再取得を
// どれだけ遅らせるかの範囲（ms）。page.tsx の initialSnapshot は revalidate=120 で
// 最大でも約2分しか経っていない実データなので、マウント直後に同じ内容をほぼ確実に
// 再取得するだけの二重フェッチ（サーバー側 SSR フェッチとクライアント側フェッチの
// back-to-back 発火）を避ける。15分ごとの定期更新ループ自体はこの遅延と無関係に
// マウント時点から起算し続ける。
export const INITIAL_REFRESH_DELAY_MIN_MS = 60_000;
export const INITIAL_REFRESH_DELAY_MAX_MS = 90_000;

/**
 * 初回バックグラウンド再取得までの遅延（ms）を決める純粋関数。
 * - `shouldPreserveInitialSeed` が false（initialSnapshot 無しのコールド CSR、または
 *   店舗/モード変更後の再実行）の場合は 0 を返す＝従来通り即時実行（挙動を変えない）。
 * - true の場合は [INITIAL_REFRESH_DELAY_MIN_MS, INITIAL_REFRESH_DELAY_MAX_MS) の範囲で
 *   ジッターさせた遅延を返す（同時にマウントされた多数のカード/タブが一斉に同じ
 *   タイミングでバックエンドを叩くのを避ける）。
 * `random` は 0 以上 1 未満の乱数を返す関数（テスト用に差し替え可能。既定は Math.random）。
 */
export function computeInitialRefreshDelayMs(
  shouldPreserveInitialSeed: boolean,
  random: () => number = Math.random,
): number {
  if (!shouldPreserveInitialSeed) return 0;
  const span = INITIAL_REFRESH_DELAY_MAX_MS - INITIAL_REFRESH_DELAY_MIN_MS;
  const r = random();
  const clamped = Number.isFinite(r) ? Math.min(Math.max(r, 0), 1) : 0;
  return INITIAL_REFRESH_DELAY_MIN_MS + Math.floor(clamped * span);
}

// page.tsx（サーバー側の initialSnapshot 取得）も today モードと同じ limit を使う必要があるため export する。
export const RANGE_LIMIT_BY_MODE: Record<PreviewRangeMode, number> = {
  // today は初速重視で軽めにして表示開始を早める
  today: 240,
  yesterday: 1200,
  lastWeek: 1200,
  custom: 1200,
};

function buildEmptySeries(): TimeSeriesPoint[] {
  const labels: string[] = [];
  for (let h = 19; h <= 24; h += 1) {
    labels.push(`${h.toString().padStart(2, "0")}:00`);
  }
  for (let h = 25; h <= 30; h += 1) {
    labels.push(`${(h - 24).toString().padStart(2, "0")}:00`);
  }
  return labels.map((label) => ({
    ts: undefined,
    label,
    menActual: null,
    womenActual: null,
    menForecast: null,
    womenForecast: null,
  }));
}

export function buildBaseSnapshot(meta: StoreMeta): StoreSnapshot {
  return {
    slug: meta.slug,
    // ブランド（オリエンタルラウンジ / 相席屋 / JIS）を店舗ごとに正しく表示する。
    // 以前は全店「オリエンタルラウンジ」固定で、相席屋店舗が誤表記されていた。
    name: buildStoreFullName(meta),
    area: meta.areaLabel,
    brand: meta.brand,
    capacity: meta.capacity,
    level: "データなし",
    nowTotal: 0,
    nowMen: 0,
    nowWomen: 0,
    peakTimeLabel: "--:--",
    peakTotal: 0,
    peakMen: null,
    peakWomen: null,
    recommendation: "データなし",
    forecastUpdatedLabel: "--:--",
    series: buildEmptySeries(),
    hasData: false,
    forecastStatus: "idle",
    latestActualTs: null,
    peakTs: null,
    completedNight: false,
  };
}

function isRangePoint(row: unknown): row is RangePoint {
  return !!row && typeof row === "object" && typeof (row as RangePoint).ts === "string";
}

export function parseRangePoints(raw: unknown): RangePoint[] {
  const obj = raw as { rows?: unknown; data?: unknown } | null | undefined;
  const rows = Array.isArray(obj?.rows) ? obj.rows : Array.isArray(obj?.data) ? obj.data : [];
  return (rows as unknown[]).filter(isRangePoint);
}

function isForecastPoint(row: unknown): row is ForecastPoint {
  return !!row && typeof row === "object" && typeof (row as ForecastPoint).ts === "string";
}

export function parseForecastPoints(raw: unknown): ForecastPoint[] {
  const obj = raw as { data?: unknown } | null | undefined;
  const rows = Array.isArray(obj?.data) ? obj.data : [];
  return (rows as unknown[]).filter(isForecastPoint);
}

// ---- re-export: 日付/JST/夜窓の純粋関数（frontend/src/lib/date/nightWindow.ts へ移設） ----
export {
  formatYMD,
  addDays,
  parseYMD,
  computeNightBaseDate,
  computeNightWindowFromBaseDate,
  computeSelectedNightBaseDate,
  isWithinNight,
  nightDateYYYYMMDD,
  isNightCompleted,
  formatNowHmJst,
} from "@/lib/date/nightWindow";

// ---- re-export: 系列構築・ピーク/鮮度分析の純粋関数（frontend/src/lib/forecast/seriesAnalysis.ts へ移設） ----
export {
  buildSeries,
  pickCurrentActual,
  pickPeak,
  hasSeriesData,
  pickLatestActualPoint,
  isPeakPassed,
  peakProgressChip,
  REALTIME_STALE_THRESHOLD_MIN,
  computeFreshness,
} from "@/lib/forecast/seriesAnalysis";
export type { FreshnessInfo } from "@/lib/forecast/seriesAnalysis";
