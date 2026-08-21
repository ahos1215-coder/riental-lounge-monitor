"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";
import { peakProgressChip } from "@/lib/forecast/seriesAnalysis";
import {
  isPercentCrowdBrand,
  seatFullnessPercent,
  seatFullnessPercentOfTotal,
} from "@/app/config/stores";

type Payload =
  | { ok: true; hasData: false }
  | { ok: true; hasData: true; href: string; title: string; updatedLabel: string; bullets: string[] }
  | { ok: false; error: string };

/**
 * peakTimeLabel / forecastUpdatedLabel が「値なし」を表すときのプレースホルダ。
 * lib/store/ssrSummary.ts の PLACEHOLDER_TIME_LABELS と同じ集合（SSR 要約と表示条件を揃える）。
 * これを弾かないと「予測更新 --:--」のような、更新時刻に見えるだけの空文字がチップになる。
 */
const PLACEHOLDER_TIME_LABELS = new Set(["", "-", "—", "--:--", "–"]);

function isMeaningfulTimeLabel(raw: string | null | undefined): boolean {
  const s = (raw ?? "").trim();
  return s.length > 0 && !PLACEHOLDER_TIME_LABELS.has(s);
}

/** リアルタイムカードの「予測ハイライト」と同じ数値から、要約用バッジ文言を最大3つ生成 */
function mlHighlightChips(
  snapshot: StoreSnapshot,
  now: Date = new Date(),
  { includeUpdated = true }: { includeUpdated?: boolean } = {},
): string[] {
  // 相席屋は在店人数を公開しておらず%のみ。ピーク要約も人数ではなく席の埋まり具合(%)で出す。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const cap = snapshot.capacity ?? 0;
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const peakTime = isMeaningfulTimeLabel(snapshot.peakTimeLabel) ? snapshot.peakTimeLabel.trim() : "";
  const updated = isMeaningfulTimeLabel(snapshot.forecastUpdatedLabel)
    ? snapshot.forecastUpdatedLabel.trim()
    : "";

  const chips: string[] = [];
  if (peak > 0 && peakTime) {
    if (percentMode) {
      const pm = snapshot.peakMen != null ? seatFullnessPercent(Math.round(snapshot.peakMen), cap) : null;
      const pw = snapshot.peakWomen != null ? seatFullnessPercent(Math.round(snapshot.peakWomen), cap) : null;
      const detail = pm != null || pw != null
        ? `男性${pm ?? 0}% / 女性${pw ?? 0}%`
        : `最大 席埋まり 約${seatFullnessPercentOfTotal(peak, cap) ?? 0}%`;
      chips.push(`ピーク目安 ${peakTime}（${detail}）`);
    } else {
      const pm = snapshot.peakMen != null ? Math.round(snapshot.peakMen) : null;
      const pw = snapshot.peakWomen != null ? Math.round(snapshot.peakWomen) : null;
      const detail = pm != null || pw != null
        ? `男性${pm ?? 0}名 / 女性${pw ?? 0}名`
        : `最大 ${peak} 人`;
      chips.push(`ピーク目安 ${peakTime}（${detail}）`);
    }
  } else if (peakTime) {
    chips.push(`ピーク目安 ${peakTime}`);
  }
  if (includeUpdated && updated) {
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

export type HighlightSection = { heading: string; chips: string[] };

/**
 * 「ハイライト（要点）」の見出しとチップを決める唯一の場所。
 *
 * 背景（2026-08-21 外部レビュー F5）: 以前はこのカードが `forecastStatus` を一切見ずに
 * チップを描画していた。予測が取れていない夜でも `peakTotal` は実測の最大値で埋まる
 * （pickPeak は実測を優先する）ため、実測ピークが「予測ハイライト」として出てしまい、
 * 同じ画面の「予測データを取得できませんでした」「今夜の予測が出たら表示されます」と
 * 矛盾していた。ここで次の3通りに割り切る。
 *
 * 1. 完了済みの夜（昨日 / 先週 / 過去日 / 夜が終わった今日）
 *    → 値は実測そのものなので「実測ハイライト」と名乗る。予測の更新時刻は出さない。
 * 2. 進行中の夜で forecastStatus === "ok"
 *    → 従来どおり「予測ハイライト」。
 * 3. それ以外（retrying / unavailable / insufficient_history / idle）
 *    → 予測はまだ無い。実測ピークを予測と名乗らせないため、セクションごと出さない
 *      （画面上部の StoreStatusMessages が理由を出している）。
 */
export function buildHighlightSection(
  snapshot: StoreSnapshot,
  now: Date = new Date(),
): HighlightSection | null {
  const completed = snapshot.completedNight === true;
  if (!completed && snapshot.forecastStatus !== "ok") return null;

  const chips = mlHighlightChips(snapshot, now, { includeUpdated: !completed });
  if (chips.length === 0) return null;

  return {
    heading: completed ? "この夜の実測ハイライト（要点）" : "予測ハイライト（要点）",
    chips,
  };
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

  const highlight = snapshot ? buildHighlightSection(snapshot, now) : null;

  return (
    <section className="rounded-2xl border border-indigo-500/20 bg-indigo-950/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          {/* 見出しは API 側で決める（前夜のレポートを翌日昼に「今日」と名乗らせないため）。
              旧レスポンス互換で title が空なら従来文言にフォールバックする。 */}
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-200/80">
            {p.title?.trim() || "今日の傾向まとめ"}
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

      {highlight && (
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <p className="mb-2 text-[10px] font-medium text-emerald-200/75">{highlight.heading}</p>
          <div className="flex flex-wrap gap-2">
            {highlight.chips.map((text, i) => (
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

