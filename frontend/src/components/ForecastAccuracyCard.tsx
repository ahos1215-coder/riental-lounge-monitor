"use client";

import { useEffect, useState } from "react";
import { isPercentCrowdBrand, type BrandId } from "@/app/config/stores";
import {
  resolveAccuracyGrade,
  resolveNightsWindow,
  resolveStoreComparison,
  type AccuracyGrade,
} from "@/lib/forecastAccuracy";

type StoreMetrics = {
  overall: { total_mae: number; men_mae: number; women_mae: number };
  weekend_night_segment?: { total_mae: number };
  rows_test: number;
};

type LiveStoreScore = {
  live_mae: number;
  matched_slots: number;
  live_baseline_mae?: number;
  ml_vs_baseline_live_pct?: number;
  /** 想定夜間来客数（相対誤差の分母）。バックエンドが予測スナップショットから算出。 */
  night_avg?: number;
  /** 店舗規模で正規化した相対誤差 = live_mae / night_avg。 */
  relative_mae?: number;
  /** ナイーブ基準(先週同時刻)に勝っているか。 */
  beats_baseline?: boolean;
};

/** バッジのランク → 表示ラベル/配色。ランク判定は resolveAccuracyGrade（純関数）。 */
const GRADE_STYLES: Record<AccuracyGrade, { label: string; color: string; bg: string }> = {
  high: { label: "高精度", color: "text-emerald-300", bg: "bg-emerald-500/15 border-emerald-500/30" },
  standard: { label: "標準", color: "text-sky-300", bg: "bg-sky-500/15 border-sky-500/30" },
  reference: { label: "参考値", color: "text-amber-300", bg: "bg-amber-500/15 border-amber-500/30" },
};

type LiveAccuracy = {
  mae_7d: number | null;
  mae_30d: number | null;
  baseline_7d: number | null;
  nights_count: number;
  updated_at?: string | null;
  stores_scored_latest?: number | null;
  per_store: Record<string, LiveStoreScore>;
};

type AccuracyResponse = {
  ok: boolean;
  trained_at?: string;
  metrics?: Record<string, StoreMetrics>;
  live?: LiveAccuracy | null;
};

let cachedResponse: AccuracyResponse | null = null;
let fetchPromise: Promise<AccuracyResponse> | null = null;

async function fetchAccuracy(): Promise<AccuracyResponse> {
  if (cachedResponse) return cachedResponse;
  if (fetchPromise) return fetchPromise;
  fetchPromise = fetch("/api/forecast_accuracy", { next: { revalidate: 3600 } })
    .then((r) => r.json() as Promise<AccuracyResponse>)
    .then((data) => {
      if (data.ok) cachedResponse = data;
      return data;
    })
    .catch(() => ({ ok: false } as AccuracyResponse))
    .finally(() => { fetchPromise = null; });
  return fetchPromise;
}

export function ForecastAccuracyCard({
  storeSlug,
  brand,
  capacity,
}: {
  storeSlug: string;
  /** 相席屋は人数非公開＝MAEも%pt表示に切替。未指定は従来どおり人 MAE 表示。 */
  brand?: BrandId;
  /** 相席屋の席数（%pt換算用）。 */
  capacity?: number | null;
}) {
  const [metrics, setMetrics] = useState<StoreMetrics | null>(null);
  const [trainedAt, setTrainedAt] = useState<string | null>(null);
  const [live, setLive] = useState<LiveAccuracy | null>(null);
  const [liveStore, setLiveStore] = useState<LiveStoreScore | null>(null);
  const percentMode = brand ? isPercentCrowdBrand(brand) && !!capacity : false;

  useEffect(() => {
    let active = true;
    // metrics（学習時 holdout）は store_id キー: 相席屋は slug==store_id ("ay_*")、
    // オリエンタルは短縮 slug に "ol_" を付与。
    const storeId = storeSlug.startsWith("ay_") ? storeSlug : `ol_${storeSlug}`;
    // live.per_store は slug キー（score_forecasts.py が by_slug 由来の slug で書き込む）。
    // オリエンタルは "ol_" を付けない短縮 slug なので、store_id で引くと必ず外れる
    // （＝オリエンタル店の実測バッジが出ないバグ）。ここは storeSlug で引く。
    fetchAccuracy().then((data) => {
      if (!active) return;
      const m = data.metrics?.[storeId] ?? null;
      setMetrics(m);
      setTrainedAt(data.trained_at ?? null);
      setLive(data.live ?? null);
      setLiveStore(data.live?.per_store?.[storeSlug] ?? null);
    });
    return () => { active = false; };
  }, [storeSlug]);

  if (!metrics) return null;

  // 相席屋は人数非公開＝MAEも「席の埋まり具合(%)」の誤差(%pt)に換算して表示する。
  // capacity は片性別の席数のため ×2 で店舗全体の座席数にする（seatFullnessPercentと同じ換算）。
  const maeUnit = percentMode ? "％pt MAE" : "人 MAE";
  const toDisplay = (v: number) =>
    percentMode && capacity ? Math.round((v / (capacity * 2)) * 100 * 10) / 10 : v;

  // 実測精度（本番の答え合わせ）を優先。この店舗の live スコアがまだ無ければ
  // 学習時の holdout metrics にフォールバックする（その場合は「参考値」であることを明示）。
  const hasLive = liveStore != null;
  const rawMae = hasLive ? liveStore.live_mae : metrics.overall.total_mae;
  const rawWeekendMae = hasLive ? undefined : metrics.weekend_night_segment?.total_mae;
  const mae = toDisplay(rawMae);
  const weekendMae = rawWeekendMae != null ? toDisplay(rawWeekendMae) : undefined;

  // バッジは「絶対人数の MAE」ではなく「店舗規模に対する相対性能」で判定する
  // （相対誤差 relative_mae + ナイーブ基準比較 beats_baseline）。これにより小規模店が
  // 小さい MAE だけで "高精度" になり、大規模店が相対的に同等以上でも "参考値" になる
  // 逆転を解消する。実測が無い店は holdout フォールバック＝参考値。
  const grade = GRADE_STYLES[resolveAccuracyGrade({
    hasLive,
    relativeMae: liveStore?.relative_mae ?? null,
    beatsBaseline: liveStore?.beats_baseline ?? null,
  })];

  const trainedLabel = trainedAt
    ? new Date(trainedAt).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo", month: "short", day: "numeric" })
    : null;

  // 実測ウィンドウ（何夜分のデータか）。mae_30d は30夜貯まるまでnullなので
  // 7日値へ安全にフォールバックしつつ、実際の集計夜数(nights_count)だけを表示する（30夜と偽らない）。
  const nightsWindow = resolveNightsWindow(live);

  // ベースライン比較は「サイト全体の平均」ではなく、この店舗自身の実測値同士で行う。
  // 全体平均だと個々の店舗の大負け／大勝ちが薄まって見えなくなるため。
  const storeComparison = resolveStoreComparison(liveStore?.live_mae, liveStore?.live_baseline_mae);
  const storeComparisonDisplay = storeComparison
    ? {
        mae: toDisplay(storeComparison.mae),
        baseline: toDisplay(storeComparison.baseline),
        worse: storeComparison.worse,
      }
    : null;

  return (
    <div className={`rounded-2xl border p-4 ${grade.bg}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-white/80">予測モデル精度</span>
        <span className={`text-[11px] font-bold ${grade.color}`}>{grade.label}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-2xl font-black text-white">{mae.toFixed(1)}</span>
        <span className="text-xs text-white/50">{maeUnit}</span>
      </div>
      <p className="mt-1 text-[11px] text-white/40">
        {hasLive
          ? `実測ベース（本番・${nightsWindow?.label ?? "集計中"}）— 前夜の予測と実測の平均的なズレ`
          : "学習時の参考値（実測精度を集計中）— 予測と実測の平均的なズレ"}
      </p>
      {hasLive ? (
        <>
          {storeComparisonDisplay && (
            <div className="mt-2 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
              <span className="text-sm font-bold text-white/70">
                ML {storeComparisonDisplay.mae.toFixed(1)} / 基準 {storeComparisonDisplay.baseline.toFixed(1)}
              </span>
              <span className="text-[11px] text-white/40">{maeUnit.replace(" MAE", "")}・実測比較</span>
              {storeComparisonDisplay.worse && (
                <span className="text-[10px] text-white/30">（現状は基準の方が近い・調整中）</span>
              )}
            </div>
          )}
          <div className="mt-3 flex items-center gap-2 text-[10px] text-white/30">
            {live?.stores_scored_latest != null && <span>直近夜: {live.stores_scored_latest}店舗</span>}
            {nightsWindow && !nightsWindow.matured && <span>30夜到達まで集計中</span>}
          </div>
        </>
      ) : (
        <>
          {weekendMae != null && (
            <div className="mt-2 flex items-baseline gap-1">
              <span className="text-sm font-bold text-white/70">{weekendMae.toFixed(1)}</span>
              <span className="text-[11px] text-white/40">{maeUnit}（週末夜）</span>
            </div>
          )}
          <div className="mt-3 flex items-center gap-2 text-[10px] text-white/30">
            <span>テスト: {metrics.rows_test}件</span>
            {trainedLabel && <span>学習: {trainedLabel}</span>}
          </div>
        </>
      )}
    </div>
  );
}
