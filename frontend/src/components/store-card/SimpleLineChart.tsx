"use client";

import { segmentIndicesByTimeGaps } from "@/lib/storeCardRangeSparkline";

export function SimpleLineChart({ points, times }: { points?: number[]; times?: number[] }) {
  const usingReal = Boolean(points && points.length >= 2);
  const normalized = usingReal ? points! : [50, 44, 52, 40, 46, 36, 44, 34, 40, 32];
  const max = Math.max(...normalized);
  const min = Math.min(...normalized);
  const span = Math.max(1, max - min);
  const step = 180 / Math.max(1, normalized.length - 1);
  const toX = (i: number) => Math.round(i * step);
  const toY = (v: number) => Math.round(60 - ((v - min) / span) * 30);
  // 実データで times が揃っているときだけ、閉店ギャップで折れ線を分割する。
  const segments =
    usingReal && times && times.length === normalized.length
      ? segmentIndicesByTimeGaps(times)
      : [normalized.map((_, i) => i)];

  return (
    <svg
      viewBox="0 0 180 72"
      className="h-20 w-full text-indigo-400/80"
      aria-hidden="true"
    >
      {segments.map((seg, si) =>
        seg.length >= 2 ? (
          <polyline
            key={si}
            points={seg.map((i) => `${toX(i)},${toY(normalized[i])}`).join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : (
          // ギャップ直後に1点だけ残るセグメント（例: 開店直後の最初の実測）は点で示す
          <circle
            key={si}
            cx={toX(seg[0])}
            cy={toY(normalized[seg[0]])}
            r={1.6}
            fill="currentColor"
          />
        ),
      )}
    </svg>
  );
}
