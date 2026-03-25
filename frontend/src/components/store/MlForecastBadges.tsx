"use client";

import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";

type Props = {
  snapshot: StoreSnapshot;
  loading?: boolean;
};

/**
 * ML 2.0 予測の要点を大きなカードではなくバッジ＋短文で表示
 */
export function MlForecastBadges({ snapshot, loading }: Props) {
  if (loading) {
    return (
      <div className="flex flex-wrap gap-2">
        <div className="h-7 w-40 animate-pulse rounded-full bg-slate-800/80" />
        <div className="h-7 w-36 animate-pulse rounded-full bg-slate-800/80" />
      </div>
    );
  }

  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const peakTime = snapshot.peakTimeLabel || "—";
  const updated = snapshot.forecastUpdatedLabel || "—";

  return (
    <div className="rounded-2xl border border-emerald-500/15 bg-emerald-950/20 px-3 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-200/80">ML 2.0 · 予測ハイライト</p>
      <p className="mt-1 text-[10px] text-slate-500">数値は参考目安です。実際の混雑は店舗の状況により変わります。</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-100/95">
          <span aria-hidden>🔥</span>
          ピーク目安 {peakTime}
          {peak > 0 ? `（最大 ${peak} 人）` : ""}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-slate-600/60 bg-slate-900/60 px-2.5 py-1 text-[11px] text-slate-300">
          予測更新 {updated}
        </span>
      </div>
    </div>
  );
}
