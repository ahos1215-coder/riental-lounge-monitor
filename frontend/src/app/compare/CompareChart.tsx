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
} from "recharts";
import { isPercentCrowdBrand, type BrandId } from "@/app/config/stores";

export type CompareChartStoreData = {
  label: string;
  brand: BrandId;
};

type CompareChartProps = {
  chartData: Record<string, unknown>[];
  selectedSlugs: string[];
  storeDataMap: Record<string, CompareChartStoreData | undefined>;
  colors: string[];
  formatTime: (ts: number) => string;
};

/**
 * 混雑推移の比較チャート（Recharts）。
 * Recharts (+d3) は First Load JS への影響が大きい（gzip 換算で ~113KB）ため、
 * /compare のページ本体からは切り離し、店舗選択後に next/dynamic(ssr:false) で
 * 遅延ロードする（店舗詳細ページの PreviewMainSection と同じパターン）。
 */
export default function CompareChart({
  chartData,
  selectedSlugs,
  storeDataMap,
  colors,
  formatTime,
}: CompareChartProps) {
  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
      <h2 className="text-lg font-bold">混雑推移の比較</h2>
      <p className="mt-1 text-xs text-white/50">
        実線 = 実測、点線 = ML 予測（相席屋は席の埋まり具合 % / オリエンタルは人数）
      </p>
      <div className="mt-4 h-72 w-full min-w-0">
        <ResponsiveContainer width="100%" height={288}>
          <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
            <XAxis
              type="number"
              dataKey="ts"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v) => formatTime(v)}
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
            />
            <YAxis
              stroke="#94a3b8"
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              label={{ value: "人 / %", angle: 0, position: "insideTopLeft", fill: "#64748b", fontSize: 10 }}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
              labelFormatter={(_, payload) => {
                const row = payload?.[0]?.payload as { label?: string } | undefined;
                return row?.label ?? "";
              }}
              formatter={(value, _name, item) => {
                const key = String(item?.dataKey ?? "");
                const slug = key.replace(/^(actual_|forecast_)/, "");
                const unit = isPercentCrowdBrand(storeDataMap[slug]?.brand ?? "oriental") ? "%" : "人";
                return [`${value}${unit}`, item?.name ?? ""];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {selectedSlugs.map((slug, i) => {
              const data = storeDataMap[slug];
              const name = data?.label ?? slug;
              const unit = isPercentCrowdBrand(data?.brand ?? "oriental") ? "%" : "人";
              return [
                <Line
                  key={`actual_${slug}`}
                  type="monotone"
                  dataKey={`actual_${slug}`}
                  name={`${name}（実測・${unit}）`}
                  stroke={colors[i]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />,
                <Line
                  key={`forecast_${slug}`}
                  type="monotone"
                  dataKey={`forecast_${slug}`}
                  name={`${name}（予測・${unit}）`}
                  stroke={colors[i]}
                  strokeWidth={1.5}
                  strokeDasharray="6 3"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />,
              ];
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
