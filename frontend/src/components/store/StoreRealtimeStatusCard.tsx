"use client";

import { GenderRatioBar } from "@/components/home/GenderRatioBar";
import type { StoreSnapshot } from "@/app/hooks/useStorePreviewData";
import { computeFreshness, crowdHintChip } from "@/app/hooks/storePreviewSnapshot";
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";

type Props = {
  snapshot: StoreSnapshot;
  loading?: boolean;
  /**
   * 鮮度計算に使う現在時刻。PreviewMainSection の now ティック（60秒毎）から渡され、
   * 15分ポーリングを待たずに「◯分前更新」が進む。未指定時は描画時の new Date()。
   */
  now?: Date;
};

/**
 * 男性・女性・男女比・混雑の目安を1枚にまとめたリアルタイムカード（モバイルの縦スクロール節約用）
 */
export function StoreRealtimeStatusCard({ snapshot, loading, now }: Props) {
  const men = Math.max(0, Math.round(Number(snapshot.nowMen ?? 0)));
  const women = Math.max(0, Math.round(Number(snapshot.nowWomen ?? 0)));
  const total = Math.max(0, Math.round(Number(snapshot.nowTotal ?? men + women)));
  // 完了済みの夜（昨日/先週/カスタム過去日）は、今夜のライブ人数を選択中の過去夜のピークと
  // 比べても無意味な比率になるため null（rank3: 「ピーク比480%」バグの修正）。
  const crowdInfo = crowdHintChip(snapshot);
  const menPct = total > 0 ? Math.round((men / total) * 100) : 50;
  const womenPct = total > 0 ? Math.round((women / total) * 100) : 50;

  // 相席屋は在店人数を公開しておらず「席の埋まり具合(%)」のみ。保存済みの推定人数から
  // %を復元してお客様には%だけを見せる（人数は非表示）。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const menFullPct = percentMode ? seatFullnessPercent(men, snapshot.capacity) : null;
  const womenFullPct = percentMode ? seatFullnessPercent(women, snapshot.capacity) : null;
  const overallFullPct =
    percentMode && snapshot.capacity
      ? seatFullnessPercent(total, snapshot.capacity * 2)
      : null;

  // リアルタイム人数の鮮度。最新実測 ts と現在時刻から「◯分前更新」を出し、しきい値以上
  // 古ければ「閉店中・最終 HH:MM 時点」に切り替える（古い数値を"今"に見せない）。
  // PreviewMainSection は ssr:false のクライアント専用なので、描画時の new Date() で
  // ハイドレーション不整合は起きない。now は親の 60 秒ティックから渡り、15分ポーリングを
  // 待たずに分数表示が進む（未指定なら computeFreshness 側の既定 new Date() を使う）。
  const freshness = computeFreshness(snapshot.latestActualTs, now);

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950/90 p-4 ring-1 ring-white/[0.04]">
        <div className="h-3 w-32 animate-pulse rounded bg-slate-800/90" />
        <div className="mt-4 flex gap-3">
          <div className="h-10 flex-1 animate-pulse rounded-xl bg-slate-800/80" />
          <div className="h-10 flex-1 animate-pulse rounded-xl bg-slate-800/80" />
        </div>
        <div className="mt-4 h-2 animate-pulse rounded-full bg-slate-800/80" />
        <div className="mt-3 h-3 w-40 animate-pulse rounded bg-slate-800/80" />
      </div>
    );
  }

  if (!snapshot.hasData && total === 0) {
    return (
      <div className="rounded-2xl border border-amber-500/20 bg-amber-950/20 px-4 py-3 text-[12px] text-amber-100/90">
        リアルタイムの人数データがまだありません。閉店時間帯か、計測待ちの可能性があります。
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-950/95 to-black/90 p-4 shadow-[0_12px_40px_rgba(0,0,0,0.45)] ring-1 ring-white/[0.05]">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">リアルタイム</p>
          {percentMode
            ? overallFullPct !== null && (
                <p className="mt-0.5 text-[11px] text-slate-400">
                  店内の埋まり具合{" "}
                  <span className="font-semibold text-slate-200">約{overallFullPct}%</span>
                </p>
              )
            : total > 0 && (
                <p className="mt-0.5 text-[11px] text-slate-400">
                  店内の目安 <span className="font-semibold text-slate-200">{total}</span> 名
                </p>
              )}
        </div>

        {/* 鮮度表示: fresh なら「◯分前更新」、stale なら閉店中/計測停止の注記。
            null（実測なし）は誤った「0分前」を避けるため何も出さない。 */}
        {freshness.state === "fresh" && (
          <p className="mt-0.5 text-[10px] text-slate-500" data-testid="realtime-freshness">
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-emerald-400/80 align-middle" aria-hidden />
            {freshness.label}
          </p>
        )}
        {freshness.state === "stale" && (
          <p
            className="mt-0.5 rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-200/90"
            data-testid="realtime-freshness"
          >
            閉店中・{freshness.label}
          </p>
        )}
      </div>

      {percentMode ? (
        <div className="mt-3">
          {/* 相席屋は在店人数を公開していないため「席の埋まり具合(%)」を大きく表示。
              人数と誤読されないよう % を大きく＋ラベルを明示する。 */}
          <p className="mb-1 text-[11px] font-semibold tracking-wide text-slate-300">
            席の埋まり具合{" "}
            <span className="font-normal text-slate-500">（人数ではありません）</span>
          </p>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="inline-flex items-baseline gap-1">
              <span className="text-[12px] font-medium text-cyan-300/90">男性</span>
              <span className="text-4xl font-black tabular-nums leading-none text-cyan-200 md:text-5xl">
                {menFullPct ?? 0}
              </span>
              <span className="text-2xl font-black leading-none text-cyan-200/80 md:text-3xl">%</span>
            </span>
            <span className="text-slate-600" aria-hidden>
              ·
            </span>
            <span className="inline-flex items-baseline gap-1">
              <span className="text-[12px] font-medium text-pink-300/90">女性</span>
              <span className="text-4xl font-black tabular-nums leading-none text-pink-200 md:text-5xl">
                {womenFullPct ?? 0}
              </span>
              <span className="text-2xl font-black leading-none text-pink-200/80 md:text-3xl">%</span>
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="inline-flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium text-cyan-300/90">男性</span>
            <span className="text-2xl font-black tabular-nums leading-none text-cyan-200 md:text-3xl">
              {men}
            </span>
            <span className="text-[11px] text-cyan-200/60">人</span>
          </span>
          <span className="text-slate-600" aria-hidden>
            ·
          </span>
          <span className="inline-flex items-baseline gap-1.5">
            <span className="text-[11px] font-medium text-pink-300/90">女性</span>
            <span className="text-2xl font-black tabular-nums leading-none text-pink-200 md:text-3xl">
              {women}
            </span>
            <span className="text-[11px] text-pink-200/60">人</span>
          </span>
        </div>
      )}

      <div className="mt-4">
        <GenderRatioBar men={men} women={women} compact percentMode={percentMode} />
        <p className="mt-1.5 text-[11px] text-slate-400">
          男女比{" "}
          <span className="font-medium text-slate-200">
            男{menPct}% / 女{womenPct}%
          </span>
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {crowdInfo && (
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] text-slate-200">
            混雑度（目安）: <span className="font-semibold text-white">{crowdInfo.crowd}</span>
            {crowdInfo.occupancyPercent !== null && (
              <span className="text-slate-400">（ピーク比 {crowdInfo.occupancyPercent}%）</span>
            )}
          </span>
        )}
        {snapshot.recommendation &&
          snapshot.recommendation !== "データなし" &&
          snapshot.recommendation !== "データ取得済み" && (
            <span className="rounded-full border border-indigo-500/25 bg-indigo-500/10 px-2.5 py-1 text-[11px] text-indigo-100/90">
              おすすめ度: {snapshot.recommendation}
            </span>
          )}
      </div>

      {percentMode && (
        <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
          ※相席屋は在店人数を公開していないため、公式サイトの「席の埋まり具合(%)」を表示しています。
        </p>
      )}
    </div>
  );
}
