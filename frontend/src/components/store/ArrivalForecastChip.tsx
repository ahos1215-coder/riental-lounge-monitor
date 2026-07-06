"use client";

import { useEffect, useState } from "react";

import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";
import type { BrandId } from "@/app/config/stores";

type NextHourPoint = {
  ts?: string;
  men_pred?: number | null;
  women_pred?: number | null;
  total_pred?: number | null;
};

type NextHourResponse = {
  ok: boolean;
  data?: NextHourPoint[];
  insufficient_history?: boolean;
  error?: string;
};

type ChipState =
  | { kind: "loading" }
  | { kind: "hidden" }
  | { kind: "ready"; arriveLabel: string; womenText: string; menText: string };

const TARGET_AHEAD_MIN = 30;

function formatHm(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** future の中から、いま(now)から見て TARGET_AHEAD_MIN 分後に最も近い点を選ぶ。 */
function pickClosestPoint(points: NextHourPoint[], now: Date): NextHourPoint | null {
  const targetMs = now.getTime() + TARGET_AHEAD_MIN * 60_000;
  let best: NextHourPoint | null = null;
  let bestDiff = Infinity;
  for (const p of points) {
    if (!p.ts) continue;
    const t = new Date(p.ts).getTime();
    if (Number.isNaN(t)) continue;
    const diff = Math.abs(t - targetMs);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = p;
    }
  }
  return best;
}

/**
 * 「着く頃(+30分)」チップ。今まで死んでいた forecast_next_hour API を使い、
 * 「いま出ると◯時着 → そのころの予測」を一言で見せる。
 * insufficient_history やエラー時は静かに何も出さない（壊れたチップを見せない）。
 */
export function ArrivalForecastChip({
  storeSlug,
  brand,
  capacity,
}: {
  storeSlug: string;
  brand: BrandId;
  capacity: number | null;
}) {
  const [state, setState] = useState<ChipState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    setState({ kind: "loading" });

    fetch(`/api/forecast_next_hour?store=${encodeURIComponent(storeSlug)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((json: NextHourResponse) => {
        if (!active) return;
        if (!json.ok || json.insufficient_history) {
          setState({ kind: "hidden" });
          return;
        }
        const points = Array.isArray(json.data) ? json.data : [];
        if (points.length === 0) {
          setState({ kind: "hidden" });
          return;
        }
        const now = new Date();
        const picked = pickClosestPoint(points, now);
        if (!picked || !picked.ts) {
          setState({ kind: "hidden" });
          return;
        }

        const percentMode = isPercentCrowdBrand(brand) && !!capacity;
        const menPred = typeof picked.men_pred === "number" ? Math.max(0, Math.round(picked.men_pred)) : null;
        const womenPred = typeof picked.women_pred === "number" ? Math.max(0, Math.round(picked.women_pred)) : null;

        if (menPred == null && womenPred == null) {
          setState({ kind: "hidden" });
          return;
        }

        const arriveLabel = formatHm(picked.ts);
        if (!arriveLabel) {
          setState({ kind: "hidden" });
          return;
        }

        let womenText: string;
        let menText: string;
        if (percentMode) {
          const womenPct = womenPred != null ? seatFullnessPercent(womenPred, capacity) : null;
          const menPct = menPred != null ? seatFullnessPercent(menPred, capacity) : null;
          womenText = womenPct != null ? `女性${womenPct}%` : "女性—";
          menText = menPct != null ? `男性${menPct}%` : "男性—";
        } else {
          womenText = womenPred != null ? `女性${womenPred}人` : "女性—";
          menText = menPred != null ? `男性${menPred}人` : "男性—";
        }

        setState({ kind: "ready", arriveLabel, womenText, menText });
      })
      .catch(() => {
        if (active) setState({ kind: "hidden" });
      });

    return () => {
      active = false;
    };
  }, [storeSlug, brand, capacity]);

  if (state.kind === "hidden") return null;

  if (state.kind === "loading") {
    return <div className="h-6 w-48 animate-pulse rounded-full bg-slate-800/60" />;
  }

  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-sky-500/25 bg-sky-500/10 px-3 py-1 text-[11px] font-medium text-sky-100/90">
      <span className="shrink-0">いま出ると {state.arriveLabel}着</span>
      <span className="text-sky-300/60" aria-hidden>
        →
      </span>
      <span className="truncate">
        予測 {state.womenText} / {state.menText}
      </span>
    </span>
  );
}
