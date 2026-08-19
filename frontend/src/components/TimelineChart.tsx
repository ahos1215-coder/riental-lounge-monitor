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
import { jstHm } from "@/lib/date/jst";

/** チャートの1点。`t` は ts の epoch ms（X軸を「時刻に比例した数値軸」にするためのキー）。 */
type ChartPoint = StoreSnapshot["series"][number] & { t: number };

/**
 * 系列に数値時刻 `t` を付与し、解釈できない ts の点は落とす。
 *
 * 背景（2026-08-20）: 以前は X 軸が「ラベル(HH:MM)のカテゴリ軸」だったため、実測（5分間隔）の
 * 区間は密、予測（15分グリッド）の区間は疎に描かれ、時間が等間隔に見えなかった
 * （例: 23:20 の実測の直後に 00:15 の予測が隣接して「ずれて見える」）。時刻に比例した数値軸に
 * することで、同じ時刻の実測と予測が横位置で一致し、未来区間も実時間どおりの幅で描かれる。
 */
function withTime(series: StoreSnapshot["series"]): ChartPoint[] {
  const out: ChartPoint[] = [];
  for (const p of series) {
    const t = p.ts ? Date.parse(p.ts) : NaN;
    if (!Number.isFinite(t)) continue;
    out.push({ ...p, t });
  }
  return out.sort((a, b) => a.t - b.t);
}

const HOUR_MS = 60 * 60 * 1000;

/** 1時間刻みの目盛り（最初の「ちょうどの時」から最後まで）。 */
function hourlyTicks(minT: number, maxT: number): number[] {
  if (!Number.isFinite(minT) || !Number.isFinite(maxT) || maxT <= minT) return [];
  const first = Math.ceil(minT / HOUR_MS) * HOUR_MS;
  const ticks: number[] = [];
  for (let t = first; t <= maxT; t += HOUR_MS) ticks.push(t);
  return ticks;
}

const formatTick = (t: number): string => jstHm(new Date(t));

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
  const data = withTime(chartData);
  const minT = data.length > 0 ? data[0].t : NaN;
  const maxT = data.length > 0 ? data[data.length - 1].t : NaN;
  const ticks = hourlyTicks(minT, maxT);
  // 予測帯の開始（実測が無く予測だけの最初の点）・終了（最後の点）・現在（最後の実測点）を
  // 数値時刻で取る。ラベル（HH:MM）は同じ時刻の実測/予測で重複し得るので数値で扱う。
  const tOf = (label: string | null, pick: "first" | "last", pred: (p: ChartPoint) => boolean) => {
    if (!label) return null;
    const arr = pick === "first" ? data : [...data].reverse();
    const hit = arr.find((p) => p.label === label && pred(p));
    return hit ? hit.t : null;
  };
  const forecastStartT = tOf(
    forecastStartLabel,
    "first",
    (p) => (p.menForecast !== null || p.womenForecast !== null) && p.menActual === null && p.womenActual === null,
  );
  const forecastEndT = forecastEndLabel ? (data.length > 0 ? maxT : null) : null;
  const currentT = tOf(currentLabel, "last", (p) => p.menActual !== null || p.womenActual !== null);
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

      {/* pt-10: グラフ上端にツールチップ専用の帯を確保する（下の Tooltip position.y=-30 がここに出る）。
          スマホで指の横にツールチップが出ると折れ線を覆って読めなかったため（2026-08-20 オーナー報告）。 */}
      <div className="relative mt-3 h-72 w-full min-w-0 rounded-2xl bg-gradient-to-b from-slate-950 via-black to-black px-3 pb-3 pt-10">
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
            data={data}
            /* top:14 — 「現在」ラベル（ReferenceLine label position=top）が上端で切れないための余白 */
            margin={{ top: 14, right: 10, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              ticks={ticks}
              tickFormatter={formatTick}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              stroke="#4b5563"
              minTickGap={22}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              stroke="#4b5563"
              allowDecimals={false}
              domain={percentMode ? [0, 100] : undefined}
              unit={percentMode ? "%" : undefined}
            />
            {/* ツールチップはグラフ枠の外（上に確保した帯）に固定し、x だけ指の位置に追従させる。
                指の真横に出ると折れ線そのものを覆って読めなくなるため（2026-08-20 オーナー報告）。 */}
            <Tooltip
              content={<TimelineTooltip unit={percentMode ? "%" : "人"} />}
              position={{ y: -32 }}
              offset={16}
              allowEscapeViewBox={{ x: false, y: true }}
              wrapperStyle={{ pointerEvents: "none", zIndex: 20 }}
            />
            <Legend content={<TimelineLegend />} />

            {forecastStartT !== null && forecastEndT !== null && (
              <ReferenceArea
                x1={forecastStartT}
                x2={forecastEndT}
                fill="#334155"
                fillOpacity={0.14}
                ifOverflow="extendDomain"
              />
            )}
            {currentT !== null && (
              <ReferenceLine
                x={currentT}
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
