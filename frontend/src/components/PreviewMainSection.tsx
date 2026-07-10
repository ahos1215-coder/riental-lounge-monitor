"use client";

import type { ReactNode } from "react";

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

        <StoreRealtimeStatusCard snapshot={snapshot} loading={!!loading} />
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
            onChangeRangeMode={onChangeRangeMode}
            customDate={customDate}
            onChangeCustomDate={onChangeCustomDate}
            selectedBaseDate={selectedBaseDate}
          />
        )}

        <LongHolidayBanner />
        <LatestForecastSummaryCard storeSlug={storeSlug} snapshot={snapshot} />
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
