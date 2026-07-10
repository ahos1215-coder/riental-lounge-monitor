"use client";

import { segmentIndicesByTimeGaps } from "@/lib/storeCardRangeSparkline";

/** 男女を同じYスケールで重ねる（カード内ミニチャート・/api/range 実測のみ） */
export function GenderTrendMiniChart({
  men,
  women,
  times,
}: {
  men: number[];
  women: number[];
  times?: number[];
}) {
  const all = [...men, ...women];
  const max = Math.max(...all, 1);
  const min = Math.min(...all);
  const span = Math.max(1, max - min);
  const width = 180;
  const n = men.length;
  const step = width / Math.max(1, n - 1);
  const toX = (i: number) => Math.round(i * step);
  const toY = (v: number) => Math.round(44 - ((v - min) / span) * 28);
  // 閉店をまたぐ大きな時間ギャップがあれば、そこで折れ線を分割する（偽の急上昇を防ぐ）。
  const segments =
    times && times.length === n
      ? segmentIndicesByTimeGaps(times)
      : [men.map((_, i) => i)];

  const renderSeries = (
    values: number[],
    strokeClass: string,
    fillClass: string,
    keyPrefix: string,
  ) =>
    segments.map((seg, si) =>
      seg.length >= 2 ? (
        <polyline
          key={`${keyPrefix}-${si}`}
          points={seg.map((i) => `${toX(i)},${toY(values[i])}`).join(" ")}
          fill="none"
          className={strokeClass}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <circle
          key={`${keyPrefix}-${si}`}
          cx={toX(seg[0])}
          cy={toY(values[seg[0]])}
          r={1.6}
          className={fillClass}
        />
      ),
    );

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
        {renderSeries(men, "stroke-cyan-300/90", "fill-cyan-300/90", "m")}
        {renderSeries(women, "stroke-pink-300/90", "fill-pink-300/90", "w")}
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
