"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";
import { peakProgressChip } from "@/app/hooks/storePreviewSnapshot";
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";

type Payload =
  | { ok: true; hasData: false }
  | { ok: true; hasData: true; href: string; title: string; updatedLabel: string; bullets: string[] }
  | { ok: false; error: string };

/** リアルタイムカードの「予測ハイライト」と同じ数値から、要約用バッジ文言を最大3つ生成 */
function mlHighlightChips(snapshot: StoreSnapshot, now: Date = new Date()): string[] {
  // 相席屋は在店人数を公開しておらず%のみ。ピーク要約も人数ではなく席の埋まり具合(%)で出す。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const cap = snapshot.capacity ?? 0;
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const peakTime = snapshot.peakTimeLabel?.trim() || "";
  const updated = snapshot.forecastUpdatedLabel?.trim() || "";

  const chips: string[] = [];
  if (peak > 0 && peakTime && peakTime !== "—") {
    if (percentMode) {
      const pm = snapshot.peakMen != null ? seatFullnessPercent(Math.round(snapshot.peakMen), cap) : null;
      const pw = snapshot.peakWomen != null ? seatFullnessPercent(Math.round(snapshot.peakWomen), cap) : null;
      const detail = pm != null || pw != null
        ? `男性${pm ?? 0}% / 女性${pw ?? 0}%`
        : `最大 席埋まり 約${seatFullnessPercent(peak, cap * 2) ?? 0}%`;
      chips.push(`ピーク目安 ${peakTime}（${detail}）`);
    } else {
      const pm = snapshot.peakMen != null ? Math.round(snapshot.peakMen) : null;
      const pw = snapshot.peakWomen != null ? Math.round(snapshot.peakWomen) : null;
      const detail = pm != null || pw != null
        ? `男性${pm ?? 0}名 / 女性${pw ?? 0}名`
        : `最大 ${peak} 人`;
      chips.push(`ピーク目安 ${peakTime}（${detail}）`);
    }
  } else if (peakTime && peakTime !== "—") {
    chips.push(`ピーク目安 ${peakTime}`);
  }
  if (updated && updated !== "—") {
    chips.push(`予測更新 ${updated}`);
  }
  // ピーク進捗チップ（ピーク前=「あと約…」/ 通過後=「ピークは過ぎました」/ 完了済みの夜=非表示）は
  // 純粋関数に集約。ピークを過ぎた後も「あと約◯人」が閉店へ向かって増える誤誘導を防ぐ。
  // now は親の 60 秒ティック由来で、ピーク通過判定（isPeakPassed）が15分ポーリングを待たず進む。
  const progressChip = peakProgressChip(snapshot, now);
  if (progressChip) {
    chips.push(progressChip);
  }
  return chips.slice(0, 3);
}

/**
 * コールド店舗（CDN MISS + バックエンド輻輳）でグラフ本体の取得を待たせないよう、
 * このカードのフェッチは「親から渡された snapshot が実データを持つ（hasData）」または
 * 「フォールバックタイマー」のどちらか早い方まで遅らせる。
 * snapshot.hasData は useStorePreviewData 側で実データ解決時にのみ true になる
 * （初期 baseSnapshot は false）ため、loading プロップが無くても main データの
 * 準備状況を近似できる。
 */
const DEFERRED_FETCH_FALLBACK_MS = 2_500;

function useDeferredFetchGate(mainReady: boolean, fallbackMs = DEFERRED_FETCH_FALLBACK_MS): boolean {
  const [timerElapsed, setTimerElapsed] = useState(mainReady);

  useEffect(() => {
    if (mainReady || timerElapsed) return;
    const t = setTimeout(() => setTimerElapsed(true), fallbackMs);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainReady, fallbackMs]);

  return mainReady || timerElapsed;
}

export function LatestForecastSummaryCard({
  storeSlug,
  snapshot,
  now,
}: {
  storeSlug: string;
  /** 予測ハイライト要点（バッジ）用。未指定なら記事要約のみ */
  snapshot?: StoreSnapshot;
  /**
   * ピーク進捗チップの時刻判定に使う現在時刻。PreviewMainSection の now ティック（60秒毎）から
   * 渡され、15分ポーリングを待たずに「ピークは過ぎました」への切替が進む。未指定時は new Date()。
   */
  now?: Date;
}) {
  const [state, setState] = useState<{ loading: boolean; payload: Payload | null }>({
    loading: true,
    payload: null,
  });

  const canFireDeferred = useDeferredFetchGate(!!snapshot?.hasData);

  useEffect(() => {
    if (!canFireDeferred) return;
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
  }, [storeSlug, canFireDeferred]);

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
  if (!p || (!p.ok && "error" in p)) {
    return (
      <section className="rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-3">
        <p className="text-[11px] text-white/30">
          予測レポートを取得できませんでした。しばらくすると自動的に更新されます。
        </p>
      </section>
    );
  }
  if (!p.ok) return null;
  if (!p.hasData) return null;

  const bullets = Array.isArray(p.bullets) ? p.bullets.filter(Boolean).slice(0, 3) : [];
  if (bullets.length === 0) return null;

  const highlightChips = snapshot ? mlHighlightChips(snapshot, now) : [];

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
    </section>
  );
}

