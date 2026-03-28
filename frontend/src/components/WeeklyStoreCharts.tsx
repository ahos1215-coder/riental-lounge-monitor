"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  BarChart,
  Cell,
} from "recharts";

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

function formatAxisTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(5, 16);
    return d.toLocaleString("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Tokyo",
    });
  } catch {
    return iso.slice(0, 16);
  }
}

export default function WeeklyStoreCharts({ store, series, topWindows, scoreThreshold }: Props) {
  const lineData = series.map((p) => ({
    ts: new Date(p.t).getTime(),
    occupancy_pct: Math.round((p.occupancy ?? 0) * 1000) / 10,
    female_pct: Math.round((p.female_ratio ?? 0) * 1000) / 10,
    label: formatAxisTime(p.t),
  }));

  const barData = topWindows.map((w, i) => ({
    name: `枠 ${i + 1}`,
    score: w.avg_score ?? 0,
    duration: w.duration_minutes != null ? Math.round(w.duration_minutes) : null,
  }));

  const scoreColor = (score: number) => {
    if (score >= scoreThreshold + 0.15) return "#a5b4fc";
    if (score >= scoreThreshold) return "#fcd34d";
    return "#94a3b8";
  };

  return (
    <div className="space-y-8">
      {lineData.length > 0 ? (
        <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
          <h2 className="text-lg font-bold text-white">時系列（間引きサンプル）</h2>
          <p className="mt-1 text-xs text-white/50">
            取得レンジ内のサンプルを最大240点に間引きしています（occupancy
            はベースライン比、女性比率は 0–100%）。店舗: {store}
          </p>
          <div className="mt-4 h-72 w-full min-h-[288px] min-w-0">
            <ResponsiveContainer width="100%" height={288} minHeight={200}>
              <LineChart data={lineData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                <XAxis
                  type="number"
                  dataKey="ts"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(v) => formatAxisTime(new Date(v).toISOString())}
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
                    const row = payload?.[0]?.payload as { label?: string } | undefined;
                    return row?.label ?? "";
                  }}
                  formatter={(value: number, name: string) => [
                    `${value}%`,
                    name === "occupancy_pct" ? "混雑度(基準比→%表示)" : "女性比率",
                  ]}
                />
                <Legend
                  wrapperStyle={{ fontSize: 12 }}
                  formatter={(value) => (value === "occupancy_pct" ? "混雑度(目安%)" : "女性比率(%)")}
                />
                <Line
                  type="monotone"
                  dataKey="occupancy_pct"
                  stroke="#818cf8"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="female_pct"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-5 text-sm text-white/55">
          <p className="font-medium text-white/70">時系列グラフ</p>
          <p className="mt-2">
            この JSON には <code className="rounded bg-white/10 px-1 text-xs">series_compact</code> がありません。
            次回の週次生成（スクリプト更新後）から表示されます。
          </p>
        </section>
      )}

      {barData.length > 0 && (
        <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
          <h2 className="text-lg font-bold text-white">Top Windows スコア</h2>
          <p className="mt-1 text-xs text-white/50">
            閾値 {scoreThreshold.toFixed(2)} を超えるほど「Good Window」として強い想定です（参考値）。
          </p>
          <div className="mt-4 h-56 w-full min-h-[224px] min-w-0">
            <ResponsiveContainer width="100%" height={224} minHeight={180}>
              <BarChart data={barData} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} horizontal={false} />
                <XAxis type="number" domain={[0, 1]} stroke="#94a3b8" tick={{ fill: "#94a3b8", fontSize: 10 }} />
                <YAxis type="category" dataKey="name" stroke="#94a3b8" tick={{ fill: "#94a3b8", fontSize: 11 }} width={56} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                  formatter={(v: number, _n, item) => {
                    const d = item?.payload?.duration as number | null;
                    const dur = d != null ? ` / 約${d}分` : "";
                    return [`${v.toFixed(3)}${dur}`, "avg_score"];
                  }}
                />
                <ReferenceLine x={scoreThreshold} stroke="#fbbf24" strokeDasharray="4 4" label={{ value: "閾値", fill: "#fbbf24", fontSize: 10 }} />
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
