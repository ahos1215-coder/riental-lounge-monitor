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
  isLoading?: boolean;
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

export function StoreCard({
  slug,
  label,
  brandLabel,
  areaLabel,
  href,
  isHighlight = false,
  stats,
  sparklinePoints,
  isLoading = false,
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
  const gender = (() => {
    const raw = stats?.genderRatio;
    if (!raw) return "-";
    const m = /^([\d.]+)\s*:\s*([\d.]+)$/.exec(raw);
    if (!m) return raw;
    return `${Math.round(Number(m[1]))}:${Math.round(Number(m[2]))}`;
  })();
  const crowd = stats?.crowdLevel ?? "-";
  const recommend = stats?.recommendLabel ?? "確認中";
  const crowdClass =
    crowd === "混雑"
      ? "text-rose-300"
      : crowd === "ほどよい"
      ? "text-amber-200"
      : crowd === "空いている"
      ? "text-sky-200"
      : "text-white";
  const crowdIcon = crowd === "混雑" ? "▲" : crowd === "ほどよい" ? "●" : crowd === "空いている" ? "○" : "・";

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
          <p className="text-[11px] font-medium text-white/60">{brandLabel}</p>
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
          {hasStats && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">ピーク予測</span>
              <span className="font-semibold text-indigo-200">{peakPredTotal}人</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <span className="text-white/50">比</span>
            <span className="font-semibold text-white">{gender}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-white/50">混雑</span>
            <span className={`font-semibold ${crowdClass}`}>{crowdIcon} {crowd}</span>
          </div>
          {hasStats && (
            <div className="flex items-center gap-1 text-right">
              <span className="text-white/50">狙い目</span>
              <span className="max-w-[7rem] truncate font-semibold text-white">{recommend}</span>
            </div>
          )}
        </div>
      </div>

      <div
        className={`mt-2 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 p-2 ${
          hasStats ? "h-16" : "h-10 opacity-70"
        }`}
      >
        <SimpleLineChart points={sparklinePoints} />
      </div>

      <p className="mt-2 text-[11px] font-medium text-indigo-300">
        店舗の詳細を見る →
      </p>
        </>
      )}
    </Link>
  );
}
