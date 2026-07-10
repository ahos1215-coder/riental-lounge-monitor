"use client";

export function LastVisitChartSkeleton() {
  return (
    <div
      className="flex h-28 w-full animate-pulse flex-col justify-end rounded-xl border border-slate-800 bg-slate-900/40 p-3"
      aria-hidden
    >
      <div className="h-16 w-full rounded-md bg-slate-800/70" />
      <div className="mt-2 flex justify-center gap-3">
        <div className="h-2 w-10 rounded bg-slate-800/70" />
        <div className="h-2 w-10 rounded bg-slate-800/70" />
      </div>
    </div>
  );
}

/** StoreCard と同系の男女ミニチャート（実測レンジ） */
export function LastVisitGenderTrendChart({ men, women }: { men: number[]; women: number[] }) {
  const all = [...men, ...women];
  const max = Math.max(...all, 1);
  const min = Math.min(...all);
  const span = Math.max(1, max - min);
  const width = 180;
  const n = men.length;
  const step = width / Math.max(1, n - 1);
  const toY = (v: number) => Math.round(44 - ((v - min) / span) * 28);
  const pathMen = men.map((v, i) => `${Math.round(i * step)},${toY(v)}`).join(" ");
  const pathWomen = women.map((v, i) => `${Math.round(i * step)},${toY(v)}`).join(" ");

  return (
    <div className="flex w-full flex-col gap-0.5">
      <svg
        viewBox="0 0 180 56"
        className="h-24 w-full shrink-0"
        role="img"
        aria-label="直近の男性・女性人数の推移（実測）"
      >
        <line x1="0" y1="50" x2="180" y2="50" className="stroke-white/[0.08]" strokeWidth={1} />
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

export function LastVisitTotalTrendChart({ points }: { points: number[] }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = Math.max(1, max - min);
  const step = 180 / Math.max(1, points.length - 1);
  const path = points
    .map((v, i) => {
      const x = Math.round(i * step);
      const y = Math.round(56 - ((v - min) / span) * 40);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg
      viewBox="0 0 180 64"
      className="h-24 w-full text-indigo-400/85"
      role="img"
      aria-label="直近の人数推移（実測・合計）"
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
