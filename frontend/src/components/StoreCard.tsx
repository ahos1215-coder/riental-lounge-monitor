"use client";

import Link from "next/link";
import { memo, useEffect, useMemo, useState } from "react";
import { GenderRatioBar } from "@/components/home/GenderRatioBar";
import { recordStoreVisit } from "@/lib/browser/meguribiStorage";
import {
  isPercentCrowdBrand,
  seatFullnessPercent,
  type BrandId,
} from "@/app/config/stores";
import { segmentIndicesByTimeGaps } from "@/lib/storeCardRangeSparkline";
import { SHOW_MEGRIBI_JUDGMENTS } from "@/lib/featureFlags";

type StoreCardProps = {
  slug: string;
  label: string;
  brandLabel: string;
  areaLabel: string;
  /** 相席屋は人数非公開＝%表示に切替。未指定は従来どおり人数表示。 */
  brand?: BrandId;
  /** 相席屋の席数（%逆算用）。 */
  capacity?: number | null;
  href?: string;
  isHighlight?: boolean;
  stats?: {
    menCount?: number;
    womenCount?: number;
    nowTotal?: number;
    peakPredTotal?: number;
    genderRatio?: string;
    crowdLevel?: string;
    recommendLabel?: string;
  };
  sparklinePoints?: number[];
  /** sparklinePoints と同順・同数の各点タイムスタンプ(epoch ms)。閉店ギャップで折れ線を分割する。 */
  sparklineTimes?: number[];
  /** 実測レンジ由来の男女推移（あれば合計1本よりこちらを優先表示） */
  sparklineMen?: number[];
  sparklineWomen?: number[];
  /** sparklineMen/Women と同順・同数の各点タイムスタンプ(epoch ms)。閉店ギャップ分割用。 */
  sparklineGenderTimes?: number[];
  /** 一覧などで /api/range だけ先に反映し、予測を後追いするとき */
  forecastPending?: boolean;
  isLoading?: boolean;
  /** めぐりびスコア 0.0〜1.0。≥0.65 → 緑 狙い目 / ≥0.40 → 黄 様子見 / <0.40 → 赤 他店へ */
  megribiScore?: number | null;
};

function SimpleLineChart({ points, times }: { points?: number[]; times?: number[] }) {
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

/** 男女を同じYスケールで重ねる（カード内ミニチャート・/api/range 実測のみ） */
function GenderTrendMiniChart({
  men,
  women,
  times,
}: {
  men: number[];
  women: number[];
  times?: number[];
}) {
  const all = [...men, ...women];
  const max = Math.max(...all, 1);
  const min = Math.min(...all);
  const span = Math.max(1, max - min);
  const width = 180;
  const n = men.length;
  const step = width / Math.max(1, n - 1);
  const toX = (i: number) => Math.round(i * step);
  const toY = (v: number) => Math.round(44 - ((v - min) / span) * 28);
  // 閉店をまたぐ大きな時間ギャップがあれば、そこで折れ線を分割する（偽の急上昇を防ぐ）。
  const segments =
    times && times.length === n
      ? segmentIndicesByTimeGaps(times)
      : [men.map((_, i) => i)];

  const renderSeries = (
    values: number[],
    strokeClass: string,
    fillClass: string,
    keyPrefix: string,
  ) =>
    segments.map((seg, si) =>
      seg.length >= 2 ? (
        <polyline
          key={`${keyPrefix}-${si}`}
          points={seg.map((i) => `${toX(i)},${toY(values[i])}`).join(" ")}
          fill="none"
          className={strokeClass}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <circle
          key={`${keyPrefix}-${si}`}
          cx={toX(seg[0])}
          cy={toY(values[seg[0]])}
          r={1.6}
          className={fillClass}
        />
      ),
    );

  return (
    <div className="flex w-full flex-col gap-0.5">
      <svg
        viewBox="0 0 180 56"
        className="h-10 w-full shrink-0"
        role="img"
        aria-label="直近の男性・女性人数の推移（実測）"
      >
        <line
          x1="0"
          y1="50"
          x2="180"
          y2="50"
          className="stroke-white/[0.08]"
          strokeWidth={1}
        />
        {renderSeries(men, "stroke-cyan-300/90", "fill-cyan-300/90", "m")}
        {renderSeries(women, "stroke-pink-300/90", "fill-pink-300/90", "w")}
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

function MegribiScoreBadge({ score }: { score: number | null | undefined }) {
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

/**
 * コールド店舗では forecast_today_multi が 7〜22秒かかることがあり、その間チップは
 * ずっと「取得中」のまま点滅し続けて「壊れている」ように見える。8秒経っても届かない場合は
 * 静かに「--」へフォールバックする（正直な表示・スピナーを回し続けない）。
 * データが後から届けば forecastPending が false になり通常表示へ自動的に戻る。
 */
const FORECAST_PENDING_TIMEOUT_MS = 8_000;

function StoreCardImpl({
  slug,
  label,
  brandLabel,
  areaLabel,
  brand,
  capacity,
  href,
  isHighlight = false,
  stats,
  sparklinePoints,
  sparklineTimes,
  sparklineMen,
  sparklineWomen,
  sparklineGenderTimes,
  forecastPending = false,
  isLoading = false,
  megribiScore,
}: StoreCardProps) {
  const resolvedHref = useMemo(
    () => href ?? `/store/${slug}?store=${slug}`,
    [href, slug],
  );

  // forecastPending が true になってから FORECAST_PENDING_TIMEOUT_MS 経っても
  // まだ pending のままなら「取得中」の点滅を諦めて「--」に切り替える。
  // slug が変わった（別カードを使い回すインスタンスではない想定だが念のため）場合や
  // forecastPending が false に戻った場合はタイムアウト状態をリセットする。
  const [pendingTimedOut, setPendingTimedOut] = useState(false);
  useEffect(() => {
    if (!forecastPending) {
      setPendingTimedOut(false);
      return;
    }
    setPendingTimedOut(false);
    const t = setTimeout(() => setPendingTimedOut(true), FORECAST_PENDING_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [forecastPending, slug]);

  const hasStats = Boolean(stats);
  const menCount = Math.max(0, Math.round(Number(stats?.menCount ?? 0)));
  const womenCount = Math.max(0, Math.round(Number(stats?.womenCount ?? 0)));
  const nowTotal = Math.max(0, Math.round(Number(stats?.nowTotal ?? menCount + womenCount)));
  const peakPredTotal = Math.max(0, Math.round(Number(stats?.peakPredTotal ?? 0)));
  const hasPeakPred = peakPredTotal > 0;

  // 相席屋は人数非公開＝席の埋まり具合(%)で表示（人数は非表示）。
  const percentMode = brand ? isPercentCrowdBrand(brand) && !!capacity : false;
  const menFullPct = percentMode ? seatFullnessPercent(menCount, capacity) ?? 0 : null;
  const womenFullPct = percentMode ? seatFullnessPercent(womenCount, capacity) ?? 0 : null;
  const peakPredPct =
    percentMode && capacity ? seatFullnessPercent(peakPredTotal, capacity * 2) ?? 0 : null;
  const gender = (() => {
    const raw = stats?.genderRatio;
    if (!raw) return "-";
    const m = /^([\d.]+)\s*:\s*([\d.]+)$/.exec(raw);
    if (!m) return raw;
    return `${Math.round(Number(m[1]))}:${Math.round(Number(m[2]))}`;
  })();
  const crowd = stats?.crowdLevel;
  const hasCrowd = crowd != null && crowd !== "—" && crowd !== "-";
  const recommend = stats?.recommendLabel;
  const hasRecommend = recommend != null && recommend !== "—" && recommend !== "-";
  const crowdClass =
    crowd === "混雑"
      ? "text-rose-300"
      : crowd === "ほどよい"
      ? "text-amber-200"
      : crowd === "空いている"
      ? "text-sky-200"
      : "text-white";
  const crowdIcon = crowd === "混雑" ? "▲" : crowd === "ほどよい" ? "●" : crowd === "空いている" ? "○" : "・";

  const hasGenderTrend =
    Array.isArray(sparklineMen) &&
    Array.isArray(sparklineWomen) &&
    sparklineMen.length >= 2 &&
    sparklineMen.length === sparklineWomen.length;
  const hasSparklineData =
    Array.isArray(sparklinePoints) && sparklinePoints.length >= 2;

  const cardClass = isHighlight
    ? "flex cursor-pointer flex-col rounded-2xl border border-indigo-500/70 bg-indigo-500/10 p-3 text-sm transition hover:bg-indigo-500/20"
    : "flex cursor-pointer flex-col rounded-2xl border border-white/10 bg-black/60 p-3 text-sm transition hover:border-white/30 hover:bg-black/70";

  const handleClick = () => {
    recordStoreVisit(slug);
  };

  return (
    <Link href={resolvedHref} className={cardClass} onClick={handleClick}>
      {isLoading ? (
        <div className="space-y-2">
          <div className="h-3 w-24 animate-pulse rounded bg-slate-700/70" />
          <div className="h-5 w-40 animate-pulse rounded bg-slate-700/70" />
          <div className="h-3 w-28 animate-pulse rounded bg-slate-800/70" />
          <div className="flex gap-2">
            <div className="h-6 w-20 animate-pulse rounded-full bg-sky-900/40" />
            <div className="h-6 w-20 animate-pulse rounded-full bg-rose-900/40" />
          </div>
          <div className="h-14 w-full animate-pulse rounded-md border border-slate-800 bg-slate-950/70" />
        </div>
      ) : (
        <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-[11px] font-medium text-white/60">{brandLabel}</p>
            {/* 判定バッジは featureFlags.ts の理由により一旦非表示 */}
            {SHOW_MEGRIBI_JUDGMENTS && <MegribiScoreBadge score={megribiScore} />}
          </div>
          <h2 className="mt-0.5 text-base font-semibold leading-tight">
            {label}
          </h2>
          <p className="mt-0.5 text-[11px] text-white/50">{areaLabel}</p>
          {hasStats && (
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="rounded-full border border-cyan-400/35 bg-cyan-500/10 px-2 py-0.5 font-semibold text-cyan-200">
                  男性 {percentMode ? `${menFullPct}%` : menCount}
                </span>
                <span className="rounded-full border border-pink-400/35 bg-pink-500/10 px-2 py-0.5 font-semibold text-pink-200">
                  女性 {percentMode ? `${womenFullPct}%` : womenCount}
                </span>
                <span className="text-white/45">
                  {percentMode ? "席の埋まり具合" : `計 ${nowTotal}`}
                </span>
              </div>
              <GenderRatioBar men={menCount} women={womenCount} compact percentMode={percentMode} />
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-0.5 text-[11px] text-white/70">
          {hasStats && (forecastPending || hasPeakPred) && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">ピーク予測</span>
              {forecastPending ? (
                <span className="font-semibold text-white/35">
                  {pendingTimedOut ? "--" : "取得中"}
                </span>
              ) : (
                <span className="font-semibold text-indigo-200">
                  {percentMode ? `約${peakPredPct}%` : `${peakPredTotal}人`}
                </span>
              )}
            </div>
          )}
          {!percentMode && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">比</span>
              <span className="font-semibold text-white">{gender}</span>
            </div>
          )}
          {/* 混雑・狙い目の判定チップは featureFlags.ts の理由により一旦非表示 */}
          {SHOW_MEGRIBI_JUDGMENTS && (forecastPending || hasCrowd) && (
            <div className="flex items-center gap-1">
              <span className="text-white/50">混雑</span>
              {forecastPending ? (
                <span className="font-semibold text-white/35">
                  {pendingTimedOut ? "--" : "取得中"}
                </span>
              ) : (
                <span className={`font-semibold ${crowdClass}`}>
                  {crowdIcon} {crowd}
                </span>
              )}
            </div>
          )}
          {SHOW_MEGRIBI_JUDGMENTS && hasStats && (forecastPending || hasRecommend) && (
            <div className="flex items-center gap-1 text-right">
              <span className="text-white/50">狙い目</span>
              {forecastPending ? (
                <span className="max-w-[7rem] truncate font-semibold text-white/35">
                  {pendingTimedOut ? "--" : "取得中"}
                </span>
              ) : (
                <span className="max-w-[7rem] truncate font-semibold text-white">{recommend}</span>
              )}
            </div>
          )}
        </div>
      </div>

      <div
        className={`mt-2 w-full overflow-hidden rounded-md border border-slate-800 bg-slate-950 px-2 py-1.5 ${
          hasStats ? "min-h-[4.25rem]" : "h-10 opacity-70"
        }`}
      >
        {!hasGenderTrend && !hasSparklineData ? (
          forecastPending ? (
            <div className="h-12 w-full animate-pulse rounded bg-slate-800/60" aria-hidden />
          ) : (
            <p className="flex min-h-12 items-center justify-center px-2 text-center text-[10px] leading-snug text-white/35">
              男女内訳つきの実測が十分に無く、推移を表示できません
            </p>
          )
        ) : hasGenderTrend ? (
          <GenderTrendMiniChart
            men={sparklineMen!}
            women={sparklineWomen!}
            times={sparklineGenderTimes}
          />
        ) : (
          <SimpleLineChart points={sparklinePoints} times={sparklineTimes} />
        )}
      </div>

      <p className="mt-2 text-[11px] font-medium text-indigo-300">
        店舗の詳細を見る →
      </p>
        </>
      )}
    </Link>
  );
}

function numArrayEqual(a?: number[], b?: number[]): boolean {
  if (a === b) return true;
  if (!a || !b) return a === b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function statsEqual(
  a: StoreCardProps["stats"],
  b: StoreCardProps["stats"],
): boolean {
  if (a === b) return true;
  if (!a || !b) return a === b;
  return (
    a.menCount === b.menCount &&
    a.womenCount === b.womenCount &&
    a.nowTotal === b.nowTotal &&
    a.peakPredTotal === b.peakPredTotal &&
    a.genderRatio === b.genderRatio &&
    a.crowdLevel === b.crowdLevel &&
    a.recommendLabel === b.recommendLabel
  );
}

/**
 * /stores は12枚のカードを並べ、各カードのデータは range_multi → megribi_score →
 * forecast_today_multi の順に非同期で個別に setState される。素の StoreCard だと
 * 1店舗分の到着のたびに親が再レンダーされ12枚全部が再評価されてしまうため、
 * memo で「自分のデータが変わった時だけ」再レンダーされるようにする。
 * 親（stores-list-client / home-client）は該当 slug のエントリだけを差し替える
 * setState を使っており、他 slug の stats/sparkline 配列は参照が保たれるが、
 * 念のため値ベースの比較にして参照の作り方に依存しないようにしている。
 */
export const StoreCard = memo(StoreCardImpl, (prev, next) => {
  return (
    prev.slug === next.slug &&
    prev.label === next.label &&
    prev.brandLabel === next.brandLabel &&
    prev.areaLabel === next.areaLabel &&
    prev.brand === next.brand &&
    prev.capacity === next.capacity &&
    prev.href === next.href &&
    prev.isHighlight === next.isHighlight &&
    prev.forecastPending === next.forecastPending &&
    prev.isLoading === next.isLoading &&
    prev.megribiScore === next.megribiScore &&
    statsEqual(prev.stats, next.stats) &&
    numArrayEqual(prev.sparklinePoints, next.sparklinePoints) &&
    numArrayEqual(prev.sparklineTimes, next.sparklineTimes) &&
    numArrayEqual(prev.sparklineMen, next.sparklineMen) &&
    numArrayEqual(prev.sparklineWomen, next.sparklineWomen) &&
    numArrayEqual(prev.sparklineGenderTimes, next.sparklineGenderTimes)
  );
});

StoreCard.displayName = "StoreCard";
