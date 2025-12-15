"use client";

import Link from "next/link";
import { useMemo } from "react";

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
};

function SimpleLineChart() {
  return (
    <svg
      viewBox="0 0 180 72"
      className="h-20 w-full text-indigo-400/80"
      aria-hidden="true"
    >
      <path
        d="M0 50 L20 44 L40 52 L60 40 L80 46 L100 36 L120 44 L140 34 L160 40 L180 32"
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
}: StoreCardProps) {
  const resolvedHref = useMemo(
    () => href ?? `/store/${slug}?store=${slug}`,
    [href, slug],
  );

  const gender = stats?.genderRatio ?? "準備中";
  const crowd = stats?.crowdLevel ?? "準備中";
  const recommend = stats?.recommendLabel ?? "準備中";

  const cardClass = isHighlight
    ? "flex cursor-pointer flex-col rounded-2xl border border-indigo-500/70 bg-indigo-500/10 p-4 text-sm transition hover:bg-indigo-500/20"
    : "flex cursor-pointer flex-col rounded-2xl border border-white/10 bg-black/60 p-4 text-sm transition hover:border-white/30 hover:bg-black/70";

  const handleClick = () => {
    try {
      window.localStorage.setItem("meguribi:lastStoreSlug", slug);
    } catch {
      // ignore
    }
  };

  return (
    <Link href={resolvedHref} className={cardClass} onClick={handleClick}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-medium text-white/60">{brandLabel}</p>
          <h2 className="mt-0.5 text-lg font-semibold leading-tight">
            {label}
          </h2>
          <p className="mt-0.5 text-[11px] text-white/50">{areaLabel}</p>
        </div>
        <div className="flex flex-col items-end gap-1 text-[11px] text-white/70">
          <div className="flex items-center gap-1">
            <span className="text-white/50">男女比</span>
            <span className="font-semibold text-white">{gender}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-white/50">混雑度</span>
            <span className="font-semibold text-white">{crowd}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-white/50">おすすめ</span>
            <span className="font-semibold text-white">{recommend}</span>
          </div>
        </div>
      </div>

      <div className="mt-3 h-20 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 p-2">
        <SimpleLineChart />
      </div>

      <p className="mt-3 text-[11px] font-medium text-indigo-300">
        ダッシュボードを開く ←
      </p>
    </Link>
  );
}
