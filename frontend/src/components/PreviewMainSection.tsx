"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { track } from "@/lib/analytics";
import SecondVenuesList from "./SecondVenuesList";
import { StoreRealtimeStatusCard } from "./store/StoreRealtimeStatusCard";
import { LatestForecastSummaryCard } from "./store/LatestForecastSummaryCard";
import { LongHolidayBanner } from "./store/LongHolidayBanner";
import { CostSimulatorCard } from "./store/CostSimulatorCard";
import TimelineChart from "./TimelineChart";
import RangeModeSelector from "./RangeModeSelector";
import StoreStatusMessages from "./StoreStatusMessages";
import type {
  PreviewRangeMode,
  StoreSnapshot,
} from "../app/hooks/useStorePreviewData";
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";
import { getStorePricing } from "@/lib/pricing";

const cardClass = "rounded-3xl border border-slate-800 bg-slate-950/80";

/**
 * 時刻依存の表示（リアルタイム鮮度「◯分前更新」・ピーク進捗チップ）を、データ再取得を
 * 待たずに最大1分の遅延で更新するための now ティック。
 *
 * 経緯: computeFreshness / peakProgressChip は描画時の now を使うが、これらを再計算させる
 * 唯一のトリガーが 15 分ごとのポーリング再描画だったため、「5分前更新」等の文言が最長15分
 * 凍結していた。ここで 60 秒ごとに now だけを更新して純粋関数へ渡す（fetch は一切走らせない）。
 * PreviewMainSection は ssr:false の dynamic import なのでサーバーでは実行されず、
 * ハイドレーション不整合も起きない。
 */
function useNowTick(intervalMs = 60_000): Date {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

type PreviewMainSectionProps = {
  storeSlug: string;
  snapshot: StoreSnapshot;
  loading?: boolean;
  error?: string | null;
  onSelectStore?: (slug: string) => void;
  rangeMode?: PreviewRangeMode;
  onChangeRangeMode?: (mode: PreviewRangeMode) => void;
  customDate?: string;
  onChangeCustomDate?: (value: string) => void;
  selectedBaseDate?: string;
  storeHeaderActions?: ReactNode;
};

export default function PreviewMainSection(props: PreviewMainSectionProps) {
  const {
    storeSlug,
    snapshot,
    loading,
    error,
    rangeMode,
    onChangeRangeMode,
    customDate = "",
    onChangeCustomDate,
    selectedBaseDate,
    storeHeaderActions,
  } = props;
  const hasData = snapshot.hasData;
  const activeRangeMode = rangeMode ?? "today";
  const canControlRange = typeof onChangeRangeMode === "function";

  // 日付レンジ（今日/昨日/先週/カスタム）の切替を GA に記録する。実際にモードが変わった時だけ
  // 1回だけ計測し、元の onChangeRangeMode の挙動はそのまま呼ぶ（UI・挙動への影響ゼロ）。
  const handleChangeRangeMode = useCallback(
    (mode: PreviewRangeMode) => {
      if (mode !== activeRangeMode) {
        track("range_mode_change", { mode });
      }
      onChangeRangeMode?.(mode);
    },
    [activeRangeMode, onChangeRangeMode],
  );

  // 鮮度・ピーク進捗の時刻依存表示を最大1分遅延で更新する now（データ再取得はしない）。
  const now = useNowTick();

  // 相席屋は在店人数を公開しておらず「席の埋まり具合(%)」表示なので、タイムラインも
  // 人数ではなく % に変換して描画する（見出しの数値と整合させる）。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const chartCap = snapshot.capacity ?? 0;
  const toChartPct = (v: number | null): number | null =>
    v == null ? null : seatFullnessPercent(v, chartCap);
  const chartData = percentMode
    ? snapshot.series.map((p) => ({
        ...p,
        menActual: toChartPct(p.menActual),
        womenActual: toChartPct(p.womenActual),
        menForecast: toChartPct(p.menForecast),
        womenForecast: toChartPct(p.womenForecast),
      }))
    : snapshot.series;
  const forecastStartLabel =
    snapshot.series.find(
      (p) =>
        (p.menForecast !== null || p.womenForecast !== null) &&
        p.menActual === null &&
        p.womenActual === null,
    )?.label ?? null;
  const forecastEndLabel = snapshot.series[snapshot.series.length - 1]?.label ?? null;
  const currentLabel =
    [...snapshot.series]
      .reverse()
      .find((p) => p.menActual !== null || p.womenActual !== null)?.label ?? null;

  // 日付切替（今日→昨日/先週/カスタム）でフェッチ中は、series が空の baseSnapshot に
  // 一旦リセットされる。以前はその間チャートが「空っぽ」に見え、コールド/低速回線では
  // 「昨日のグラフが表示されない（＝壊れている）」と誤認されていた。実測点がまだ 1 つも
  // 無い読み込み中はチャート面にローディングを重ねて、空表示と区別できるようにする。
  const hasAnySeriesPoint = snapshot.series.some(
    (p) =>
      p.menActual !== null ||
      p.womenActual !== null ||
      p.menForecast !== null ||
      p.womenForecast !== null,
  );
  const showChartLoading = !!loading && !hasAnySeriesPoint;

  // 料金シミュレーターは対応データがある店舗のみ表示（オリエンタルラウンジ36店舗対応）。
  // 「今夜の入店の目安」は today モードで予測が取得できている時だけ算出する。
  const pricing = getStorePricing(storeSlug);
  const hasForecastForSim = activeRangeMode === "today" && snapshot.forecastStatus === "ok";

  return (
    <div className="flex w-full min-w-0 flex-col gap-5">
      {/* ① 今どうなの？ — 統合リアルタイム */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs">
            <p className="text-[11px] text-slate-400">今見ている店舗</p>
            <p className="text-sm font-semibold text-slate-100">
              {snapshot.area} / {snapshot.name}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {storeHeaderActions}
            <StoreStatusMessages
              loading={loading}
              error={error}
              hasData={hasData}
              forecastStatus={snapshot.forecastStatus}
            />
          </div>
        </div>

        <StoreRealtimeStatusCard snapshot={snapshot} loading={!!loading} now={now} />
      </section>

      {/* ② この後どうなる？ — 日付切替 + タイムライン（キラーコンテンツ） */}
      <section className="space-y-3">
        <TimelineChart
          percentMode={percentMode}
          chartData={chartData}
          forecastStartLabel={forecastStartLabel}
          forecastEndLabel={forecastEndLabel}
          currentLabel={currentLabel}
          showChartLoading={showChartLoading}
        />

        {canControlRange && (
          <RangeModeSelector
            activeRangeMode={activeRangeMode}
            onChangeRangeMode={handleChangeRangeMode}
            customDate={customDate}
            onChangeCustomDate={onChangeCustomDate}
            selectedBaseDate={selectedBaseDate}
          />
        )}

        <LongHolidayBanner />
        <LatestForecastSummaryCard storeSlug={storeSlug} snapshot={snapshot} now={now} />
      </section>

      {/* ③ 料金の目安 — 対応データがある店舗のみ（プロトタイプ: 長崎店） */}
      {pricing && (
        <section className="space-y-3">
          <CostSimulatorCard
            pricing={pricing}
            series={snapshot.series}
            hasForecast={hasForecastForSim}
          />
        </section>
      )}

      {/* ④ フィードバック・二次会（下位） */}
      <section className={`${cardClass} p-3 text-xs`}>
        <SecondVenuesList storeSlug={storeSlug} />
      </section>
    </div>
  );
}
