"use client";

import { useEffect, useState } from "react";
import { GenderRatioBar } from "@/components/home/GenderRatioBar";
import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";

function crowdHintFromTotals(nowTotal: number, peakTotal: number): string {
  if (peakTotal <= 0) return "予測データ待ち";
  const r = nowTotal / peakTotal;
  if (r >= 0.85) return "混雑に近い目安";
  if (r >= 0.45) return "ほどよい目安";
  return "空いている目安";
}

/**
 * 「正直な鮮度」表示: 最新実測データの ts から経過分を計算し、鮮度バッジ文言を返す。
 * 30分を超えたら「最終計測」表現にして、あたかも今の値かのように見せない。
 */
function freshnessLabel(latestActualTs: string | null, nowMs: number): string | null {
  if (!latestActualTs) return null;
  const t = new Date(latestActualTs).getTime();
  if (Number.isNaN(t)) return null;
  const diffMin = Math.max(0, Math.round((nowMs - t) / 60000));
  if (diffMin <= 0) return "たった今更新";
  if (diffMin < 30) return `${diffMin}分前更新`;
  if (diffMin < 60) return `最終計測 ${diffMin}分前`;
  const diffHour = Math.round(diffMin / 60);
  return `最終計測 約${diffHour}時間前`;
}

/**
 * 鮮度バッジ。SSR時点と初回クライアント描画時点で経過時間の計算結果がズレる
 * （ハイドレーションミスマッチになる）のを避けるため、mounted になるまでは何も出さず
 * useEffect 後に描画する。60秒ごとに再計算してバッジを生きた状態に保つ。
 */
function FreshnessBadge({ latestActualTs }: { latestActualTs: string | null }) {
  const [nowMs, setNowMs] = useState<number | null>(null);

  useEffect(() => {
    setNowMs(Date.now());
    const timer = setInterval(() => setNowMs(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  if (nowMs === null) return null;
  const label = freshnessLabel(latestActualTs, nowMs);
  if (!label) return null;

  const isStale = (() => {
    if (!latestActualTs) return false;
    const t = new Date(latestActualTs).getTime();
    if (Number.isNaN(t)) return false;
    return nowMs - t > 30 * 60000;
  })();

  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        isStale
          ? "border-amber-500/30 bg-amber-500/10 text-amber-200/90"
          : "border-emerald-500/25 bg-emerald-500/10 text-emerald-200/90",
      ].join(" ")}
      title="最新の実測データが取得された時刻からの経過時間"
    >
      <span
        className={["h-1.5 w-1.5 rounded-full", isStale ? "bg-amber-400" : "bg-emerald-400"].join(" ")}
        aria-hidden
      />
      {label}
    </span>
  );
}

type Props = {
  snapshot: StoreSnapshot;
  loading?: boolean;
};

/**
 * 男性・女性・男女比・混雑の目安を1枚にまとめたリアルタイムカード（モバイルの縦スクロール節約用）
 */
export function StoreRealtimeStatusCard({ snapshot, loading }: Props) {
  const men = Math.max(0, Math.round(Number(snapshot.nowMen ?? 0)));
  const women = Math.max(0, Math.round(Number(snapshot.nowWomen ?? 0)));
  const total = Math.max(0, Math.round(Number(snapshot.nowTotal ?? men + women)));
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const crowd = crowdHintFromTotals(total, peak);
  const occupancy = peak > 0 ? Math.round((total / peak) * 100) : null;
  const menPct = total > 0 ? Math.round((men / total) * 100) : 50;
  const womenPct = total > 0 ? Math.round((women / total) * 100) : 50;

  // 相席屋は在店人数を公開しておらず「席の埋まり具合(%)」のみ。保存済みの推定人数から
  // %を復元してお客様には%だけを見せる（人数は非表示）。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const menFullPct = percentMode ? seatFullnessPercent(men, snapshot.capacity) : null;
  const womenFullPct = percentMode ? seatFullnessPercent(women, snapshot.capacity) : null;
  const overallFullPct =
    percentMode && snapshot.capacity
      ? seatFullnessPercent(total, snapshot.capacity * 2)
      : null;

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950/90 p-4 ring-1 ring-white/[0.04]">
        <div className="h-3 w-32 animate-pulse rounded bg-slate-800/90" />
        <div className="mt-4 flex gap-3">
          <div className="h-10 flex-1 animate-pulse rounded-xl bg-slate-800/80" />
          <div className="h-10 flex-1 animate-pulse rounded-xl bg-slate-800/80" />
        </div>
        <div className="mt-4 h-2 animate-pulse rounded-full bg-slate-800/80" />
        <div className="mt-3 h-3 w-40 animate-pulse rounded bg-slate-800/80" />
      </div>
    );
  }

  if (!snapshot.hasData && total === 0) {
    return (
      <div className="rounded-2xl border border-amber-500/20 bg-amber-950/20 px-4 py-3 text-[12px] text-amber-100/90">
        リアルタイムの人数データがまだありません。閉店時間帯か、計測待ちの可能性があります。
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">リアルタイム</p>
          {percentMode
            ? overallFullPct !== null && (
                <p className="mt-0.5 text-[11px] text-slate-400">
                  店内の埋まり具合{" "}
                  <span className="font-semibold text-slate-200">約{overallFullPct}%</span>
                </p>
              )
            : total > 0 && (
                <p className="mt-0.5 text-[11px] text-slate-400">
                  店内の目安 <span className="font-semibold text-slate-200">{total}</span> 名
                </p>
              )}
        </div>
        <FreshnessBadge latestActualTs={snapshot.latestActualTs} />
      </div>

      {percentMode ? (
        <div className="mt-3">
          {/* 相席屋は在店人数を公開していないため「席の埋まり具合(%)」を大きく表示。
              人数と誤読されないよう % を大きく＋ラベルを明示する。 */}
          <p className="mb-1 text-[11px] font-semibold tracking-wide text-slate-300">
            席の埋まり具合{" "}
            <span className="font-normal text-slate-500">（人数ではありません）</span>
          </p>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="inline-flex items-baseline gap-1">
              <span className="text-[12px] font-medium text-cyan-300/90">男性</span>
              <span className="text-4xl font-black tabular-nums leading-none text-cyan-200 md:text-5xl">
                {menFullPct ?? 0}
              </span>
              <span className="text-2xl font-black leading-none text-cyan-200/80 md:text-3xl">%</span>
            </span>
            <span className="text-slate-600" aria-hidden>
              ·
            </span>
            <span className="inline-flex items-baseline gap-1">
              <span className="text-[12px] font-medium text-pink-300/90">女性</span>
              <span className="text-4xl font-black tabular-nums leading-none text-pink-200 md:text-5xl">
                {womenFullPct ?? 0}
              </span>
              <span className="text-2xl font-black leading-none text-pink-200/80 md:text-3xl">%</span>
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="inline-flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium text-cyan-300/90">男性</span>
            <span className="text-2xl font-black tabular-nums leading-none text-cyan-200 md:text-3xl">
              {men}
            </span>
            <span className="text-[11px] text-cyan-200/60">人</span>
          </span>
          <span className="text-slate-600" aria-hidden>
            ·
          </span>
          <span className="inline-flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium text-pink-300/90">女性</span>
            <span className="text-2xl font-black tabular-nums leading-none text-pink-200 md:text-3xl">
              {women}
            </span>
            <span className="text-[11px] text-pink-200/60">人</span>
          </span>
        </div>
      )}

      <div className="mt-4">
        <GenderRatioBar men={men} women={women} compact percentMode={percentMode} />
        <p className="mt-1.5 text-[11px] text-slate-400">
          男女比{" "}
          <span className="font-medium text-slate-200">
            男{menPct}% / 女{womenPct}%
          </span>
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] text-slate-200">
          混雑度（目安）: <span className="font-semibold text-white">{crowd}</span>
          {occupancy !== null && (
            <span className="text-slate-400">（ピーク比 {occupancy}%）</span>
          )}
        </span>
        {snapshot.recommendation &&
          snapshot.recommendation !== "データなし" &&
          snapshot.recommendation !== "データ取得済み" && (
            <span className="rounded-full border border-indigo-500/25 bg-indigo-500/10 px-2.5 py-1 text-[11px] text-indigo-100/90">
              おすすめ度: {snapshot.recommendation}
            </span>
          )}
      </div>

      {percentMode && (
        <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
          ※相席屋は在店人数を公開していないため、公式サイトの「席の埋まり具合(%)」を表示しています。
        </p>
      )}
    </div>
  );
}
