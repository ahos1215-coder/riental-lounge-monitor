import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type TimeSeriesPoint = {
  label: string;
  menActual: number;
  womenActual: number;
  menForecast: number;
  womenForecast: number;
};

type Props = {
  storeName: string;
  men: number;
  women: number;
  level: string;
  recommendation: string;
  peakTimeLabel: string;
  peakTotal: number;
  series: TimeSeriesPoint[];
};

export function MainChartSection({
  storeName,
  men,
  women,
  level,
  recommendation,
  peakTimeLabel,
  peakTotal,
  series,
}: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-400">今見ている店舗</p>
          <h1 className="text-xl font-bold text-white">{storeName}</h1>
          <p className="text-xs text-slate-500 mt-1">
            男性 {men} 人 / 女性 {women} 人 ・ 混雑度: {level}
          </p>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-200">
          <p>おすすめ</p>
          <p className="text-slate-100 font-semibold">{recommendation}</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 shadow-lg">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-400">19:00 〜 05:00 推移</p>
            <p className="text-lg font-semibold text-white">実測 & 予測（男女別）</p>
          </div>
          <div className="text-xs text-slate-500">
            ピーク: {peakTimeLabel} / {peakTotal} 人
          </div>
        </div>

        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="label" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #1f2937",
                  color: "#e2e8f0",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="menActual"
                name="男性（実測）"
                fill="#38bdf8"
                stroke="#38bdf8"
                fillOpacity={0.12}
              />
              <Area
                type="monotone"
                dataKey="womenActual"
                name="女性（実測）"
                fill="#f472b6"
                stroke="#f472b6"
                fillOpacity={0.12}
              />
              <Line
                type="monotone"
                dataKey="menForecast"
                name="男性（予測）"
                stroke="#38bdf8"
                strokeDasharray="5 4"
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="womenForecast"
                name="女性（予測）"
                stroke="#f472b6"
                strokeDasharray="5 4"
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
