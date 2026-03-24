"use client";

import Link from "next/link";
import { useMemo } from "react";
import { recordStoreVisit } from "@/lib/browser/meguribiStorage";

type StoreCardProps = {
  slug: string;
  label: string;
  brandLabel: string;
  areaLabel: string;
  href?: string;
  isHighlight?: boolean;
  stats?: {
    genderRatio?: string;
    crowdLevel?: string;
    recommendLabel?: string;
  };
  sparklinePoints?: number[];
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
}: StoreCardProps) {
  const resolvedHref = useMemo(
    () => href ?? `/store/${slug}?store=${slug}`,
    [href, slug],
  );

  const hasStats = Boolean(stats);
  const gender = (() => {
    const raw = stats?.genderRatio;
    if (!raw) return "-";
    const m = /^([\d.]+)\s*:\s*([\d.]+)$/.exec(raw);
    if (!m) return raw;
    return `${Math.round(Number(m[1]))}:${Math.round(Number(m[2]))}`;
  })();
  const crowd = stats?.crowdLevel ?? "-";
  const recommend = stats?.recommendLabel ?? "-";
  const crowdClass =
    crowd === "混雑"
      ? "text-rose-300"
      : crowd === "ほどよい"
      ? "text-amber-200"
      : crowd === "空いている"
      ? "text-sky-200"
      : "text-white";

  const cardClass = isHighlight
    ? "flex cursor-pointer flex-col rounded-2xl border border-indigo-500/70 bg-indigo-500/10 p-3 text-sm transition hover:bg-indigo-500/20"
    : "flex cursor-pointer flex-col rounded-2xl border border-white/10 bg-black/60 p-3 text-sm transition hover:border-white/30 hover:bg-black/70";

  const handleClick = () => {
    recordStoreVisit(slug);
  };

  return (
    <Link href={resolvedHref} className={cardClass} onClick={handleClick}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium text-white/60">{brandLabel}</p>
          <h2 className="mt-0.5 text-base font-semibold leading-tight">
            {label}
          </h2>
          <p className="mt-0.5 text-[11px] text-white/50">{areaLabel}</p>
        </div>
        <div className="flex flex-col items-end gap-0.5 text-[11px] text-white/70">
          <div className="flex items-center gap-1">
            <span className="text-white/50">男女比</span>
            <span className="font-semibold text-white">{gender}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-white/50">混雑度</span>
            <span className={`font-semibold ${crowdClass}`}>{crowd}</span>
          </div>
          {hasStats && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">おすすめ</span>
              <span className="font-semibold text-white">{recommend}</span>
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
        ダッシュボードを開く ←
      </p>
    </Link>
  );
}
