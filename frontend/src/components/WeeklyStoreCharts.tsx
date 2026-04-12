"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  BarChart,
  Cell,
} from "recharts";

import { formatAxisDate, formatTooltipTime, formatWindowTime } from "@/lib/dateFormat";

export type SeriesCompactPoint = {
  t: string;
  occupancy: number;
  female_ratio: number;
};

export type TopWindowChart = {
  start?: string;
  end?: string;
  duration_minutes?: number;
  avg_score?: number;
};

type Props = {
  store: string;
  series: SeriesCompactPoint[];
  topWindows: TopWindowChart[];
  scoreThreshold: number;
};

export default function WeeklyStoreCharts({ series, topWindows, scoreThreshold }: Props) {
  const lineData = series.map((p) => ({
    ts: new Date(p.t).getTime(),
    occupancy_pct: Math.round((p.occupancy ?? 0) * 1000) / 10,
    female_pct: Math.round((p.female_ratio ?? 0) * 1000) / 10,
    rawIso: p.t,
  }));

  const barData = topWindows.map((w, i) => ({
    name: `#${i + 1}`,
    label: `${formatWindowTime(w.start)} 〜`,
    score: w.avg_score ?? 0,
    duration: w.duration_minutes != null ? Math.round(w.duration_minutes) : null,
  }));

  const scoreLabel = (score: number) => {
    if (score >= scoreThreshold + 0.15) return "とても賑わう";
    if (score >= scoreThreshold) return "賑わいあり";
    return "やや混む";
  };

  const scoreColor = (score: number) => {
    if (score >= scoreThreshold + 0.15) return "#a5b4fc";
    if (score >= scoreThreshold) return "#fcd34d";
    return "#94a3b8";
  };

  return (
    <div className="space-y-8">
      {lineData.length > 0 ? (
        <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
          <h2 className="text-lg font-bold text-white">1 週間の混雑推移</h2>
          <p className="mt-1 text-xs text-white/50">
            過去 1 週間の混雑度と女性比率の推移です。ピンクの線が高いほど女性比率が高い時間帯です。
          </p>
          <div className="mt-4 h-72 w-full min-h-[288px] min-w-0">
            <ResponsiveContainer width="100%" height={288} minHeight={200}>
              <LineChart data={lineData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                <XAxis
                  type="number"
                  dataKey="ts"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(v) => formatAxisDate(new Date(v).toISOString())}
                  stroke="#94a3b8"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                />
                <YAxis
                  domain={[0, 100]}
                  stroke="#94a3b8"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  label={{ value: "%", angle: 0, position: "insideTopLeft", fill: "#64748b", fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                  labelFormatter={(_, payload) => {
                    const row = payload?.[0]?.payload as { rawIso?: string } | undefined;
                    return row?.rawIso ? formatTooltipTime(row.rawIso) : "";
                  }}
                  formatter={(value: number, name: string) => [
                    `${value}%`,
                    name === "occupancy_pct" ? "混雑度" : "女性比率",
                  ]}
                />
                <Legend
                  wrapperStyle={{ fontSize: 12 }}
                  formatter={(value) => (value === "occupancy_pct" ? "混雑度" : "女性比率")}
                />
                <Line
                  type="monotone"
                  dataKey="occupancy_pct"
                  stroke="#818cf8"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  name="occupancy_pct"
                />
                <Line
                  type="monotone"
                  dataKey="female_pct"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  name="female_pct"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-[10px] text-white/40">
            <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-[#818cf8]" />混雑度: 高いほど人が多い</span>
            <span><span className="mr-1 inline-block h-2 w-4 rounded-sm bg-[#f472b6]" />女性比率: 高いほど女性が多い</span>
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-5 text-sm text-white/55">
          <p className="font-medium text-white/70">グラフデータなし</p>
          <p className="mt-2">
            次回の週次生成から表示されます。
          </p>
        </section>
      )}

      {barData.length > 0 && (
        <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
          <h2 className="text-lg font-bold text-white">賑わいスコア</h2>
          <p className="mt-1 text-xs text-white/50">
            スコアが高いほど、その時間帯は安定して賑わっていた傾向です。
          </p>
          <div className="mt-4 h-56 w-full min-h-[224px] min-w-0">
            <ResponsiveContainer width="100%" height={224} minHeight={180}>
              <BarChart data={barData} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} horizontal={false} />
                <XAxis type="number" domain={[0, 1]} stroke="#94a3b8" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <YAxis type="category" dataKey="name" stroke="#94a3b8" tick={{ fill: "#94a3b8", fontSize: 11 }} width={36} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                  formatter={(v: number, _n, item) => {
                    const d = item?.payload?.duration as number | null;
                    const lbl = item?.payload?.label as string | undefined;
                    const dur = d != null ? `約${d}分間` : "";
                    const time = lbl ?? "";
                    return [`${scoreLabel(v)}（${time} ${dur}）`, "賑わい度"];
                  }}
                />
                <Bar dataKey="score" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {barData.map((e, i) => (
                    <Cell key={`c-${i}`} fill={scoreColor(e.score)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  );
}
