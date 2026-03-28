"use client";

import Link from "next/link";
import { useMemo } from "react";
import { GenderRatioBar } from "@/components/home/GenderRatioBar";
import { recordStoreVisit } from "@/lib/browser/meguribiStorage";

type StoreCardProps = {
  slug: string;
  label: string;
  brandLabel: string;
  areaLabel: string;
  href?: string;
  isHighlight?: boolean;
  stats?: {
    menCount?: number;
    womenCount?: number;
    nowTotal?: number;
    peakPredTotal?: number;
    genderRatio?: string;
    crowdLevel?: string;
    recommendLabel?: string;
  };
  sparklinePoints?: number[];
  /** 実測レンジ由来の男女推移（あれば合計1本よりこちらを優先表示） */
  sparklineMen?: number[];
  sparklineWomen?: number[];
  /** 一覧などで /api/range だけ先に反映し、予測を後追いするとき */
  forecastPending?: boolean;
  isLoading?: boolean;
  /** めぐりびスコア 0.0〜1.0。≥0.65 → 緑 狙い目 / ≥0.40 → 黄 様子見 / <0.40 → 赤 他店へ */
  megribiScore?: number | null;
};

function SimpleLineChart({ points }: { points?: number[] }) {
  const normalized = points && points.length >= 2 ? points : [50, 44, 52, 40, 46, 36, 44, 34, 40, 32];
  const max = Math.max(...normalized);
  const min = Math.min(...normalized);
  const span = Math.max(1, max - min);
  const step = 180 / Math.max(1, normalized.length - 1);
  const path = normalized
    .map((v, i) => {
      const x = Math.round(i * step);
      const y = Math.round(60 - ((v - min) / span) * 30);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg
      viewBox="0 0 180 72"
      className="h-20 w-full text-indigo-400/80"
      aria-hidden="true"
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** 男女を同じYスケールで重ねる（カード内ミニチャート・/api/range 実測のみ） */
function GenderTrendMiniChart({ men, women }: { men: number[]; women: number[] }) {
  const all = [...men, ...women];
  const max = Math.max(...all, 1);
  const min = Math.min(...all);
  const span = Math.max(1, max - min);
  const width = 180;
  const n = men.length;
  const step = width / Math.max(1, n - 1);
  const toY = (v: number) => Math.round(44 - ((v - min) / span) * 28);
  const pathMen = men
    .map((v, i) => `${Math.round(i * step)},${toY(v)}`)
    .join(" ");
  const pathWomen = women
    .map((v, i) => `${Math.round(i * step)},${toY(v)}`)
    .join(" ");

  return (
    <div className="flex w-full flex-col gap-0.5">
      <svg
        viewBox="0 0 180 56"
        className="h-10 w-full shrink-0"
        role="img"
        aria-label="直近の男性・女性人数の推移（実測）"
      >
        <line
          x1="0"
          y1="50"
          x2="180"
          y2="50"
          className="stroke-white/[0.08]"
          strokeWidth={1}
        />
        <polyline
          points={pathMen}
          fill="none"
          className="stroke-cyan-300/90"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <polyline
          points={pathWomen}
          fill="none"
          className="stroke-pink-300/90"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="flex justify-center gap-3 text-[9px] leading-none text-white/40">
        <span className="flex items-center gap-1">
          <span className="h-0.5 w-2.5 rounded-full bg-cyan-300/90" aria-hidden />
          男性
        </span>
        <span className="flex items-center gap-1">
          <span className="h-0.5 w-2.5 rounded-full bg-pink-300/90" aria-hidden />
          女性
        </span>
        <span className="text-white/30">実測・直近</span>
      </div>
    </div>
  );
}

function MegribiScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  if (score >= 0.65)
    return (
      <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-500/40">
        ● 狙い目
      </span>
    );
  if (score >= 0.40)
    return (
      <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300 ring-1 ring-amber-500/40">
        ● 様子見
      </span>
    );
  return (
    <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-300 ring-1 ring-rose-500/40">
      ● 他店へ
    </span>
  );
}

export function StoreCard({
  slug,
  label,
  brandLabel,
  areaLabel,
  href,
  isHighlight = false,
  stats,
  sparklinePoints,
  sparklineMen,
  sparklineWomen,
  forecastPending = false,
  isLoading = false,
  megribiScore,
}: StoreCardProps) {
  const resolvedHref = useMemo(
    () => href ?? `/store/${slug}?store=${slug}`,
    [href, slug],
  );

  const hasStats = Boolean(stats);
  const menCount = Math.max(0, Math.round(Number(stats?.menCount ?? 0)));
  const womenCount = Math.max(0, Math.round(Number(stats?.womenCount ?? 0)));
  const nowTotal = Math.max(0, Math.round(Number(stats?.nowTotal ?? menCount + womenCount)));
  const peakPredTotal = Math.max(0, Math.round(Number(stats?.peakPredTotal ?? 0)));
  const hasPeakPred = peakPredTotal > 0;
  const gender = (() => {
    const raw = stats?.genderRatio;
    if (!raw) return "-";
    const m = /^([\d.]+)\s*:\s*([\d.]+)$/.exec(raw);
    if (!m) return raw;
    return `${Math.round(Number(m[1]))}:${Math.round(Number(m[2]))}`;
  })();
  const crowd = stats?.crowdLevel;
  const hasCrowd = crowd != null && crowd !== "—" && crowd !== "-";
  const recommend = stats?.recommendLabel;
  const hasRecommend = recommend != null && recommend !== "—" && recommend !== "-";
  const crowdClass =
    crowd === "混雑"
      ? "text-rose-300"
      : crowd === "ほどよい"
      ? "text-amber-200"
      : crowd === "空いている"
      ? "text-sky-200"
      : "text-white";
  const crowdIcon = crowd === "混雑" ? "▲" : crowd === "ほどよい" ? "●" : crowd === "空いている" ? "○" : "・";

  const hasGenderTrend =
    Array.isArray(sparklineMen) &&
    Array.isArray(sparklineWomen) &&
    sparklineMen.length >= 2 &&
    sparklineMen.length === sparklineWomen.length;
  const hasSparklineData =
    Array.isArray(sparklinePoints) && sparklinePoints.length >= 2;

  const cardClass = isHighlight
    ? "flex cursor-pointer flex-col rounded-2xl border border-indigo-500/70 bg-indigo-500/10 p-3 text-sm transition hover:bg-indigo-500/20"
    : "flex cursor-pointer flex-col rounded-2xl border border-white/10 bg-black/60 p-3 text-sm transition hover:border-white/30 hover:bg-black/70";

  const handleClick = () => {
    recordStoreVisit(slug);
  };

  return (
    <Link href={resolvedHref} className={cardClass} onClick={handleClick}>
      {isLoading ? (
        <div className="space-y-2">
          <div className="h-3 w-24 animate-pulse rounded bg-slate-700/70" />
          <div className="h-5 w-40 animate-pulse rounded bg-slate-700/70" />
          <div className="h-3 w-28 animate-pulse rounded bg-slate-800/70" />
          <div className="flex gap-2">
            <div className="h-6 w-20 animate-pulse rounded-full bg-sky-900/40" />
            <div className="h-6 w-20 animate-pulse rounded-full bg-rose-900/40" />
          </div>
          <div className="h-14 w-full animate-pulse rounded-md border border-slate-800 bg-slate-950/70" />
        </div>
      ) : (
        <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-[11px] font-medium text-white/60">{brandLabel}</p>
            <MegribiScoreBadge score={megribiScore} />
          </div>
          <h2 className="mt-0.5 text-base font-semibold leading-tight">
            {label}
          </h2>
          <p className="mt-0.5 text-[11px] text-white/50">{areaLabel}</p>
          {hasStats && (
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="rounded-full border border-cyan-400/35 bg-cyan-500/10 px-2 py-0.5 font-semibold text-cyan-200">
                  男性 {menCount}
                </span>
                <span className="rounded-full border border-pink-400/35 bg-pink-500/10 px-2 py-0.5 font-semibold text-pink-200">
                  女性 {womenCount}
                </span>
                <span className="text-white/45">計 {nowTotal}</span>
              </div>
              <GenderRatioBar men={menCount} women={womenCount} compact />
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-0.5 text-[11px] text-white/70">
          {hasStats && (forecastPending || hasPeakPred) && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">ピーク予測</span>
              {forecastPending ? (
                <span className="font-semibold text-white/35">取得中</span>
              ) : (
                <span className="font-semibold text-indigo-200">{peakPredTotal}人</span>
              )}
            </div>
          )}
          <div className="flex items-center gap-1">
            <span className="text-white/50">比</span>
            <span className="font-semibold text-white">{gender}</span>
          </div>
          {(forecastPending || hasCrowd) && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">混雑</span>
              {forecastPending ? (
                <span className="font-semibold text-white/35">取得中</span>
              ) : (
                <span className={`font-semibold ${crowdClass}`}>
                  {crowdIcon} {crowd}
                </span>
              )}
            </div>
          )}
          {hasStats && (forecastPending || hasRecommend) && (
            <div className="flex items-center gap-1 text-right">
              <span className="text-white/50">狙い目</span>
              {forecastPending ? (
                <span className="max-w-[7rem] truncate font-semibold text-white/35">取得中</span>
              ) : (
                <span className="max-w-[7rem] truncate font-semibold text-white">{recommend}</span>
              )}
            </div>
          )}
        </div>
      </div>

      <div
        className={`mt-2 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 px-2 py-1.5 ${
          hasStats ? "min-h-[4.25rem]" : "h-10 opacity-70"
        }`}
      >
        {!hasGenderTrend && !hasSparklineData ? (
          forecastPending ? (
            <div className="h-12 w-full animate-pulse rounded bg-slate-800/60" aria-hidden />
          ) : (
            <p className="flex min-h-12 items-center justify-center px-2 text-center text-[10px] leading-snug text-white/35">
              男女内訳つきの実測が十分に無く、推移を表示できません
            </p>
          )
        ) : hasGenderTrend ? (
          <GenderTrendMiniChart men={sparklineMen!} women={sparklineWomen!} />
        ) : (
          <SimpleLineChart points={sparklinePoints} />
        )}
      </div>

      <p className="mt-2 text-[11px] font-medium text-indigo-300">
        店舗の詳細を見る →
      </p>
        </>
      )}
    </Link>
  );
}
