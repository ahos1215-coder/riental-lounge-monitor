"use client";

import { useEffect, useState } from "react";

type StoreMetrics = {
  overall: { total_mae: number; men_mae: number; women_mae: number };
  weekend_night_segment?: { total_mae: number };
  rows_test: number;
};

type AccuracyResponse = {
  ok: boolean;
  trained_at?: string;
  metrics?: Record<string, StoreMetrics>;
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

export function ForecastAccuracyCard({ storeSlug }: { storeSlug: string }) {
  const [metrics, setMetrics] = useState<StoreMetrics | null>(null);
  const [trainedAt, setTrainedAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const storeId = `ol_${storeSlug}`;
    fetchAccuracy().then((data) => {
      if (!active) return;
      const m = data.metrics?.[storeId] ?? null;
      setMetrics(m);
      setTrainedAt(data.trained_at ?? null);
    });
    return () => { active = false; };
  }, [storeSlug]);

  if (!metrics) return null;

  const mae = metrics.overall.total_mae;
  const weekendMae = metrics.weekend_night_segment?.total_mae;

  const grade =
    mae <= 5 ? { label: "高精度", color: "text-emerald-300", bg: "bg-emerald-500/15 border-emerald-500/30" }
    : mae <= 10 ? { label: "標準", color: "text-sky-300", bg: "bg-sky-500/15 border-sky-500/30" }
    : { label: "参考値", color: "text-amber-300", bg: "bg-amber-500/15 border-amber-500/30" };

  const trainedLabel = trainedAt
    ? new Date(trainedAt).toLocaleDateString("ja-JP", { timeZone: "Asia/Tokyo", month: "short", day: "numeric" })
    : null;

  return (
    <div className={`rounded-2xl border p-4 ${grade.bg}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-white/80">予測モデル精度</span>
        <span className={`text-[11px] font-bold ${grade.color}`}>{grade.label}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-2xl font-black text-white">{mae.toFixed(1)}</span>
        <span className="text-xs text-white/50">人 MAE</span>
      </div>
      <p className="mt-1 text-[11px] text-white/40">平均絶対誤差 — 予測と実測の平均的なズレ</p>
      {weekendMae != null && (
        <div className="mt-2 flex items-baseline gap-1">
          <span className="text-sm font-bold text-white/70">{weekendMae.toFixed(1)}</span>
          <span className="text-[11px] text-white/40">人 MAE（週末夜）</span>
        </div>
      )}
      <div className="mt-3 flex items-center gap-2 text-[10px] text-white/30">
        <span>テスト: {metrics.rows_test}件</span>
        {trainedLabel && <span>学習: {trainedLabel}</span>}
      </div>
    </div>
  );
}
