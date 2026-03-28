"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";

type Payload =
  | { ok: true; hasData: false }
  | { ok: true; hasData: true; href: string; title: string; updatedLabel: string; bullets: string[] }
  | { ok: false; error: string };

/** リアルタイムカードの「予測ハイライト」と同じ数値から、要約用バッジ文言を最大3つ生成 */
function mlHighlightChips(snapshot: StoreSnapshot): string[] {
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const total = Math.max(0, Math.round(Number(snapshot.nowTotal ?? 0)));
  const peakTime = snapshot.peakTimeLabel?.trim() || "";
  const updated = snapshot.forecastUpdatedLabel?.trim() || "";
  const delta = peak > 0 ? Math.max(0, peak - total) : 0;
  const rec = snapshot.recommendation?.trim() || "";

  const chips: string[] = [];
  if (peak > 0 && peakTime && peakTime !== "—") {
    const pm = snapshot.peakMen != null ? Math.round(snapshot.peakMen) : null;
    const pw = snapshot.peakWomen != null ? Math.round(snapshot.peakWomen) : null;
    const detail = pm != null || pw != null
      ? `男性${pm ?? 0}名 / 女性${pw ?? 0}名`
      : `最大 ${peak} 人`;
    chips.push(`ピーク目安 ${peakTime}（${detail}）`);
  } else if (peakTime && peakTime !== "—") {
    chips.push(`ピーク目安 ${peakTime}`);
  }
  if (updated && updated !== "—") {
    chips.push(`予測更新 ${updated}`);
  }
  if (delta > 0) {
    chips.push(`ピークまで あと約${delta}人`);
  } else if (rec && rec !== "データなし" && rec !== "データ取得済み") {
    chips.push(`おすすめ度 ${rec}`);
  }
  return chips.slice(0, 3);
}

export function LatestForecastSummaryCard({
  storeSlug,
  snapshot,
}: {
  storeSlug: string;
  /** 予測ハイライト要点（バッジ）用。未指定なら記事要約のみ */
  snapshot?: StoreSnapshot;
}) {
  const [state, setState] = useState<{ loading: boolean; payload: Payload | null }>({
    loading: true,
    payload: null,
  });

  useEffect(() => {
    let mounted = true;
    (async () => {
      setState({ loading: true, payload: null });
      try {
        const res = await fetch(`/api/blog/latest-store-summary?store=${encodeURIComponent(storeSlug)}`, {
          cache: "no-store",
        });
        const json = (await res.json()) as Payload;
        if (!mounted) return;
        setState({ loading: false, payload: json });
      } catch {
        if (!mounted) return;
        setState({ loading: false, payload: { ok: false, error: "fetch failed" } });
      }
    })();
    return () => {
      mounted = false;
    };
  }, [storeSlug]);

  if (state.loading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
        <div className="h-3 w-40 animate-pulse rounded bg-slate-800/80" />
        <div className="mt-3 space-y-2">
          <div className="h-3 w-full animate-pulse rounded bg-slate-800/70" />
          <div className="h-3 w-11/12 animate-pulse rounded bg-slate-800/70" />
          <div className="h-3 w-10/12 animate-pulse rounded bg-slate-800/70" />
        </div>
      </section>
    );
  }

  const p = state.payload;
  if (!p || !p.ok) return null;
  if (!p.hasData) return null;

  const bullets = Array.isArray(p.bullets) ? p.bullets.filter(Boolean).slice(0, 3) : [];
  if (bullets.length === 0) return null;

  const highlightChips = snapshot ? mlHighlightChips(snapshot) : [];

  return (
    <section className="rounded-2xl border border-indigo-500/20 bg-indigo-950/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-200/80">
            今日の傾向まとめ
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">更新: {p.updatedLabel}</p>
        </div>
        <Link
          href={p.href}
          className="rounded-full border border-indigo-400/30 bg-indigo-500/10 px-3 py-1.5 text-[11px] font-semibold text-indigo-100/90 hover:border-indigo-300/60 hover:bg-indigo-500/15"
        >
          続きを読む →
        </Link>
      </div>

      {highlightChips.length > 0 && (
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <p className="mb-2 text-[10px] font-medium text-emerald-200/75">予測ハイライト（要点）</p>
          <div className="flex flex-wrap gap-2">
            {highlightChips.map((text, i) => (
              <span
                key={`${i}-${text.slice(0, 12)}`}
                className="inline-flex max-w-full items-center rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-medium text-emerald-100/90"
              >
                <span className="truncate">{text}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <ul className="mt-3 space-y-1.5 text-[12px] leading-relaxed text-slate-200/90">
        {bullets.map((b, i) => (
          <li key={`${i}-${b.slice(0, 16)}`} className="flex gap-2">
            <span className="mt-[2px] h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-300/80" aria-hidden />
            <span>{b}</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[10px] text-slate-500">
        記事は自動生成です。まずはタイムラインの点線（予測）で全体傾向を確認するのがおすすめです。
      </p>
    </section>
  );
}

