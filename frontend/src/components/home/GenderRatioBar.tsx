"use client";

type GenderRatioBarProps = {
  men: number;
  women: number;
  /** コンパクト（カード内） */
  compact?: boolean;
  className?: string;
};

/**
 * 男女比を視覚化するスタックバー。男性 cyan 系・女性 pink 系（ダーク UI 向けネオン）。
 */
export function GenderRatioBar({ men, women, compact = false, className = "" }: GenderRatioBarProps) {
  const m = Math.max(0, Math.round(men));
  const w = Math.max(0, Math.round(women));
  const total = m + w;
  const menPct = total > 0 ? (m / total) * 100 : 50;
  const womenPct = 100 - menPct;

  const barH = compact ? "h-1.5" : "h-3";
  const glow =
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]";

  return (
    <div className={`w-full ${className}`}>
      <div
        className={`flex ${barH} w-full overflow-hidden rounded-full bg-slate-900/90 ring-1 ring-white/10 ${glow}`}
        role="img"
        aria-label={`男女比 男性${m}人 女性${w}人`}
      >
        <div
          className="min-w-[2px] bg-gradient-to-b from-cyan-300 to-cyan-600 shadow-[0_0_16px_rgba(34,211,238,0.45)] transition-[width] duration-500 ease-out"
          style={{ width: `${menPct}%` }}
        />
        <div
          className="min-w-[2px] bg-gradient-to-b from-pink-400 to-fuchsia-600 shadow-[0_0_14px_rgba(244,114,182,0.4)] transition-[width] duration-500 ease-out"
          style={{ width: `${womenPct}%` }}
        />
      </div>
      {!compact && (
        <div className="mt-2 flex justify-between text-[11px] tabular-nums tracking-tight">
          <span className="font-medium text-cyan-300/95">男性側 {menPct < 10 ? menPct.toFixed(1) : Math.round(menPct)}%</span>
          <span className="font-medium text-pink-300/95">女性側 {womenPct < 10 ? womenPct.toFixed(1) : Math.round(womenPct)}%</span>
        </div>
      )}
    </div>
  );
}
