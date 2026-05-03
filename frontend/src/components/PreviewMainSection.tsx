"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type LegendProps,
  type TooltipProps,
} from "recharts";

import SecondVenuesList from "./SecondVenuesList";
import { StoreRealtimeStatusCard } from "./store/StoreRealtimeStatusCard";
import { LatestForecastSummaryCard } from "./store/LatestForecastSummaryCard";
import { LongHolidayBanner } from "./store/LongHolidayBanner";
import type {
  PreviewRangeMode,
  StoreSnapshot,
} from "../app/hooks/useStorePreviewData";

const cardClass = "rounded-3xl border border-slate-800 bg-slate-950/80";

const RANGE_MODE_OPTIONS: { id: PreviewRangeMode; label: string }[] = [
  { id: "today", label: "今日" },
  { id: "yesterday", label: "昨日" },
  { id: "lastWeek", label: "先週" },
  { id: "custom", label: "カスタム" },
];

type TimelinePayloadEntry = {
  name?: string;
  value?: number | null;
  color?: string;
};

type TimelineTooltipProps = TooltipProps<number, string> & {
  label?: string | number;
  payload?: TimelinePayloadEntry[];
};

type TimelineLegendPayloadItem = {
  value?: string | number;
  color?: string;
};
type TimelineLegendProps = LegendProps & {
  payload?: TimelineLegendPayloadItem[];
};

function TimelineLegend(props: TimelineLegendProps) {
  const payload = props.payload;
  const items = Array.isArray(payload) ? payload : [];
  if (!items.length) return null;
  const labels: Record<string, string> = {
    "女性：予測": "女性 · 予測",
    "女性：実測": "女性 · 実測",
    "男性：予測": "男性 · 予測",
    "男性：実測": "男性 · 実測",
  };
  const order: Record<string, number> = {
    "女性：予測": 0,
    "女性：実測": 1,
    "男性：予測": 2,
    "男性：実測": 3,
  };
  const filtered = items
    .filter((entry) => {
      const raw = (entry?.value ?? "").toString();
      return raw in labels;
    })
    .sort((a, b) => {
      const av = (a?.value ?? "").toString();
      const bv = (b?.value ?? "").toString();
      return (order[av] ?? 99) - (order[bv] ?? 99);
    });
  if (!filtered.length) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10px] text-slate-300">
      {filtered.map((entry, idx) => {
        const raw = (entry?.value ?? "").toString();
        const value = labels[raw] ?? raw;
        const color = entry?.color ?? "#cbd5e1";
        return (
          <span key={`${value}-${idx}`} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-[2px] w-3 rounded"
              style={{ backgroundColor: color }}
            />
            <span>{value}</span>
          </span>
        );
      })}
    </div>
  );
}

function TimelineTooltip({ active, payload, label = "" }: TimelineTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const labels: Record<string, string> = {
    "男性：実測": "男性（実測）",
    "女性：実測": "女性（実測）",
    "男性：予測": "男性（予測）",
    "女性：予測": "女性（予測）",
  };

  const filtered = payload.filter((entry) => {
    const name = entry.name ?? "";
    return !!labels[name];
  });
  if (!filtered.length) return null;

  return (
    <div
      style={{
        backgroundColor: "#020617",
        border: "1px solid #1f2937",
        borderRadius: 8,
        fontSize: 11,
        padding: "6px 8px",
      }}
    >
      <p style={{ marginBottom: 4, color: "#e5e7eb" }}>{label}</p>

      {filtered.map((entry, idx) => {
        const name = entry.name ?? "";
        const raw = entry.value;

        let valueText = "-";
        if (typeof raw === "number") {
          valueText = Math.round(raw).toString();
        }

        const color = entry.color ?? "#e5e7eb";

        return (
          <p key={`${name}-${idx}`} style={{ color }}>
            {labels[name] ?? name}: {valueText}
          </p>
        );
      })}
    </div>
  );
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

  
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  const openDatePicker = () => {
    const el =
      dateInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!el) return;
    el.focus();
    el.showPicker?.();
  };

  const [isClient, setIsClient] = useState(false);
  useEffect(() => setIsClient(true), []);

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
            {loading && <p className="text-[10px] text-slate-500">データ取得中…</p>}
            {error && (
              <p className="max-w-[14rem] text-[10px] text-rose-400">
                データ取得に失敗しました（ベース表示中）
              </p>
            )}
            {!loading && !error && !hasData && (
              <p className="max-w-[14rem] text-[10px] text-amber-300">
                データがまだありません。計測待ちか、閉店時間帯の可能性があります。
              </p>
            )}
            {!loading && !error && hasData && snapshot.forecastStatus === "retrying" && (
              <p className="max-w-[16rem] text-[10px] text-sky-300">
                予測データを再取得しています…
              </p>
            )}
            {!loading && !error && hasData && snapshot.forecastStatus === "unavailable" && (
              <p className="max-w-[16rem] text-[10px] text-amber-300">
                予測データを取得できませんでした。実測グラフのみ表示しています。
              </p>
            )}
          </div>
        </div>

        <StoreRealtimeStatusCard snapshot={snapshot} loading={!!loading} />
      </section>

      {/* ② この後どうなる？ — 日付切替 + タイムライン（キラーコンテンツ） */}
      <section className="space-y-3">
        <div className="rounded-3xl border border-slate-800 bg-black p-3 shadow-[0_18px_60px_rgba(0,0,0,0.85)]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">timeline</p>
              <p className="mt-0.5 text-[11px] text-slate-400">
                19:00-05:00 の推移（実測 &amp; 予測 / 男性・女性）
              </p>
            </div>
            <div className="text-right">
              <p className="text-[11px] text-slate-500">
                実線=実測 / 点線=予測（データなしの時間帯は空欄）
              </p>
            </div>
          </div>

          <div className="mt-3 h-72 w-full min-w-0 rounded-2xl bg-gradient-to-b from-slate-950 via-black to-black p-3">
            {isClient && (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={snapshot.series}
                  margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10, fill: "#9ca3af" }}
                    stroke="#4b5563"
                    minTickGap={22}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#9ca3af" }}
                    stroke="#4b5563"
                    allowDecimals={false}
                  />
                  <Tooltip content={<TimelineTooltip />} />
                  <Legend content={<TimelineLegend />} />

                  {forecastStartLabel && forecastEndLabel && (
                    <ReferenceArea
                      x1={forecastStartLabel}
                      x2={forecastEndLabel}
                      fill="#334155"
                      fillOpacity={0.14}
                      ifOverflow="extendDomain"
                    />
                  )}
                  {currentLabel && (
                    <ReferenceLine
                      x={currentLabel}
                      stroke="#94a3b8"
                      strokeDasharray="3 3"
                      strokeOpacity={0.8}
                      label={{
                        value: "現在",
                        position: "top",
                        fill: "#94a3b8",
                        fontSize: 10,
                      }}
                    />
                  )}

                  <Area
                    type="monotone"
                    dataKey="menActual"
                    stroke="none"
                    fill="#38bdf8"
                    fillOpacity={0.24}
                    connectNulls
                    legendType="none"
                  />
                  <Area
                    type="monotone"
                    dataKey="womenActual"
                    stroke="none"
                    fill="#f472b6"
                    fillOpacity={0.24}
                    connectNulls
                    legendType="none"
                  />

                  <Line
                    type="monotone"
                    dataKey="menActual"
                    name="男性：実測"
                    stroke="#38bdf8"
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="womenActual"
                    name="女性：実測"
                    stroke="#f472b6"
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />

                  <Line
                    type="monotone"
                    dataKey="menForecast"
                    name="男性：予測"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={false}
                    strokeDasharray="5 4"
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="womenForecast"
                    name="女性：予測"
                    stroke="#f472b6"
                    strokeWidth={2.5}
                    dot={false}
                    strokeDasharray="5 4"
                    connectNulls
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {canControlRange && (
          <div className="flex flex-col gap-2 rounded-2xl border border-slate-800/70 bg-slate-950/40 px-3 py-2">
            <p className="text-[10px] text-slate-500">表示する日の夜（19:00–05:00）</p>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-wrap items-center gap-1">
                {RANGE_MODE_OPTIONS.map((opt) => {
                  const active = activeRangeMode === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        onChangeRangeMode(opt.id);
                        if (opt.id === "custom") openDatePicker();
                      }}
                      className={[
                        "rounded-full border px-3 py-1 text-[11px] font-semibold transition",
                        active
                          ? "border-amber-300/80 bg-amber-400/10 text-amber-100"
                          : "border-slate-700 bg-slate-950 text-slate-200 hover:border-slate-500",
                      ].join(" ")}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-2 md:ml-auto">
                <input
                  ref={dateInputRef}
                  type="date"
                  value={customDate}
                  onChange={(e) => {
                    const next = e.target.value;
                    onChangeCustomDate?.(next);
                    onChangeRangeMode("custom");
                  }}
                  className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                />
                {selectedBaseDate && (
                  <span className="text-[11px] text-slate-500">
                    表示: {selectedBaseDate}（19:00-05:00）
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        <LongHolidayBanner />
        <LatestForecastSummaryCard storeSlug={storeSlug} snapshot={snapshot} />
      </section>

      {/* ④ フィードバック・二次会（下位） */}
      <section className={`${cardClass} p-3 text-xs`}>
        <SecondVenuesList storeSlug={storeSlug} />
      </section>
    </div>
  );
}
