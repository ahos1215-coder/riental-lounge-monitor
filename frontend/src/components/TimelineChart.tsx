"use client";

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
} from "recharts";

import { TimelineLegend, TimelineTooltip } from "./TimelineChartParts";
import type { StoreSnapshot } from "../app/hooks/useStorePreviewData";

type TimelineChartProps = {
  percentMode: boolean;
  chartData: StoreSnapshot["series"];
  forecastStartLabel: string | null;
  forecastEndLabel: string | null;
  currentLabel: string | null;
  showChartLoading: boolean;
};

export default function TimelineChart({
  percentMode,
  chartData,
  forecastStartLabel,
  forecastEndLabel,
  currentLabel,
  showChartLoading,
}: TimelineChartProps) {
  return (
    <div className="rounded-3xl border border-slate-800 bg-black p-3 shadow-[0_18px_60px_rgba(0,0,0,0.85)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">timeline</p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {percentMode
              ? "19:00-05:00 の席の埋まり具合%（実測 & 予測 / 男性・女性）"
              : "19:00-05:00 の推移（実測 & 予測 / 男性・女性）"}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] text-slate-500">
            実線=実測 / 点線=予測（データなしの時間帯は空欄）
          </p>
        </div>
      </div>

      <div className="relative mt-3 h-72 w-full min-w-0 rounded-2xl bg-gradient-to-b from-slate-950 via-black to-black p-3">
        {/* 日付切替のフェッチ中（まだ実測/予測点が 1 つも無い）はチャート面にローディングを
            重ねる。空グラフと「読み込み中」を見た目で区別でき、コールド/低速回線で
            「昨日のグラフが出ない＝壊れている」という誤認を防ぐ（グラフ自体の描画は下の
            ResponsiveContainer がそのまま担い、線のスタイル・色は一切変えない）。 */}
        {showChartLoading && (
          <div
            className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-2xl bg-black/40"
            role="status"
            aria-live="polite"
            data-testid="timeline-loading"
          >
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400" />
            <span className="text-[11px] text-slate-300">グラフを読み込み中…</span>
          </div>
        )}
        {/* PreviewMainSection 自体が dynamic(ssr:false) の対象なので、この時点で常にクライアント側。
            以前あった isClient ゲートは冗長で、マウント後1フレーム余計にチャート描画を遅らせていた。 */}
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
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
              domain={percentMode ? [0, 100] : undefined}
              unit={percentMode ? "%" : undefined}
            />
            <Tooltip content={<TimelineTooltip unit={percentMode ? "%" : "人"} />} />
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
      </div>
    </div>
  );
}
