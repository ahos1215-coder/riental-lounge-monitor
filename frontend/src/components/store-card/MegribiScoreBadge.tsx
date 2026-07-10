"use client";

export function MegribiScoreBadge({ score }: { score: number | null | undefined }) {
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
