"use client";

import { useEffect, useState } from "react";

import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";
import {
  MEGRIBI_SCORE_NOTE,
  VERDICT_TONE_CLASSES,
  crowdHintFromTotals,
  formatFreshness,
  movementHint,
  peakTimingFromTs,
  verdictFromScore,
} from "@/lib/megribiVerdict";

type MegribiScoreItem = {
  slug: string;
  score: number;
  total: number | null;
  men: number | null;
  women: number | null;
  female_ratio: number;
  men_seat_pct: number | null;
  women_seat_pct: number | null;
  ts?: string;
};

type ScoreState = {
  loading: boolean;
  item: MegribiScoreItem | null;
};

/**
 * 「今夜の評決」カード — ストアページのグラフの上に置く、答えファーストの一枚。
 * megribi_score（既存の 0.65/0.40 しきい値）から評決バッジを出し、
 * その根拠となる実測値（女性比・混雑度・ピーク予測）を1行で添える。
 *
 * 「AIが言っている」ではなく「データがこうだから」の形にするため、
 * バッジの下に必ず数字の根拠を並べる（BRAND PRINCIPLE）。
 */
export function TonightVerdictCard({ storeSlug, snapshot }: { storeSlug: string; snapshot: StoreSnapshot }) {
  const [state, setState] = useState<ScoreState>({ loading: true, item: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, item: null });
    fetch(`/api/megribi_score?store=${encodeURIComponent(storeSlug)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((json: { ok?: boolean; data?: MegribiScoreItem[] }) => {
        if (!active) return;
        const item = json.ok && Array.isArray(json.data) ? json.data[0] ?? null : null;
        setState({ loading: false, item });
      })
      .catch(() => {
        if (active) setState({ loading: false, item: null });
      });
    return () => {
      active = false;
    };
  }, [storeSlug]);

  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const cap = snapshot.capacity ?? 0;
  const nowTotal = Math.max(0, Math.round(Number(snapshot.nowTotal ?? 0)));
  const peakTotal = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const peakTimeLabel = snapshot.peakTimeLabel?.trim() || "";
  const hasPeak = !!peakTimeLabel && peakTimeLabel !== "--:--" && peakTotal > 0;

  // 営業時間外・計測待ちなど「今はライブ実測が無い」状態。予測があれば前向きな見出しに切り替える。
  const hasLiveNow = snapshot.hasData && nowTotal > 0;

  const score = state.item?.score ?? null;
  const verdict = verdictFromScore(hasLiveNow ? score : null);

  // 女性比：相席屋は% (women_seat_pct)、他ブランドは megribi_score API の female_ratio から。
  const femalePctFromApi =
    state.item?.female_ratio != null ? Math.round(state.item.female_ratio * 100) : null;
  const femalePct = percentMode
    ? state.item?.women_seat_pct ?? seatFullnessPercent(snapshot.nowWomen, cap)
    : femalePctFromApi;

  const crowd = hasLiveNow ? crowdHintFromTotals(nowTotal, peakTotal) : null;
  const timing = peakTimingFromTs(snapshot.peakTs);
  const movement = hasPeak ? movementHint(peakTimeLabel, timing) : null;
  const freshness = formatFreshness(snapshot.latestActualTs);

  // 根拠の一行を組み立てる。データが揃っている分だけ繋ぐ（無理に埋めない）。
  const readoutParts: string[] = [];
  if (hasLiveNow) {
    if (femalePct != null) readoutParts.push(`女性比 ${femalePct}%`);
    if (crowd) readoutParts.push(crowd);
    if (hasPeak) readoutParts.push(`ピーク予測 ${peakTimeLabel}`);
  } else if (hasPeak) {
    // 営業時間外/計測待ちでも予測があれば、それを前面に出す。
    readoutParts.push(`今夜のピーク予測 ${peakTimeLabel}`);
  }
  const readout = readoutParts.join("・");

  const headline = hasLiveNow
    ? verdict.label
    : hasPeak
      ? "今は営業時間外の可能性"
      : "計測待ち";

  const tone = hasLiveNow ? verdict.tone : "neutral";
  const toneClasses = VERDICT_TONE_CLASSES[tone];

  return (
    <div
      className={`rounded-3xl border ${toneClasses.border} bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_16px_50px_rgba(0,0,0,0.5)] ring-1 ring-white/[0.04]`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-500">今夜の評決</p>
        {freshness && (
          <span
            className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
              freshness.isFresh
                ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-200/90"
                : "border-slate-600/40 bg-slate-800/40 text-slate-400"
            }`}
          >
            {freshness.label}
          </span>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center rounded-full px-3 py-1 text-[13px] font-bold ${toneClasses.badge}`}>
          {headline}
        </span>
      </div>

      {readout && (
        <p className="mt-2.5 text-[13px] leading-relaxed text-slate-200">
          {readout}
        </p>
      )}

      {!readout && !state.loading && (
        <p className="mt-2.5 text-[12px] leading-relaxed text-slate-400">
          実測・予測データを準備中です。しばらくすると表示されます。
        </p>
      )}

      {movement && (
        <p className="mt-1.5 text-[12px] text-slate-400">{movement}</p>
      )}

      <p className="mt-3 border-t border-white/[0.06] pt-2 text-[10px] leading-relaxed text-white/50">
        {MEGRIBI_SCORE_NOTE}
      </p>
    </div>
  );
}
