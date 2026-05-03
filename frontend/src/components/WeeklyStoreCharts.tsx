"use client";

import {
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  BarChart,
  Cell,
} from "recharts";

import { formatWindowTime } from "@/lib/dateFormat";

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
  series: SeriesCompactPoint[]; // 互換のため残置 (現在は未使用)
  topWindows: TopWindowChart[];
  scoreThreshold: number;
};

/**
 * Weekly Report の賑わいスコア棒グラフ。
 *
 * v2 (2026-05): 折れ線グラフ「1 週間の混雑推移」は WeeklyHeatmap に置換したため削除。
 * ここでは top_windows の Bar Chart のみを描画する。
 */
export default function WeeklyStoreCharts({ topWindows, scoreThreshold }: Props) {
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

  if (barData.length === 0) {
    return null;
  }

  return (
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
            <YAxis
              type="category"
              dataKey="name"
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              width={36}
            />
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
  );
}
