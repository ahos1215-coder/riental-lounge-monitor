"use client";

import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  LineElement,
  CategoryScale,
  LinearScale,
  PointElement,
  Tooltip,
  Legend,
} from "chart.js";
import type { ForecastPoint as BaseForecastPoint } from "./ForecastNextHourChart";

ChartJS.register(
  LineElement,
  CategoryScale,
  LinearScale,
  PointElement,
  Tooltip,
  Legend,
);

// Combined 用: ForecastPoint に total_actual を足したもの
export type CombinedPoint = BaseForecastPoint & {
  total_actual?: number | null;
};

type Props = {
  points: CombinedPoint[];
};

function formatTimeLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const h = d.getHours().toString().padStart(2, "0");
  const m = d.getMinutes().toString().padStart(2, "0");
  return `${h}:${m}`;
}

export default function ForecastPreviewChart({ points }: Props) {
  if (!points || points.length === 0) {
    return (
      <div className="rounded border border-slate-200 bg-slate-900/40 p-4 text-sm text-slate-400">
        データがありません。
      </div>
    );
  }

  // 時刻順にソートしてからラベルとデータを作る
  const sorted = [...points].sort((a, b) => {
    const ta = new Date(a.ts).getTime();
    const tb = new Date(b.ts).getTime();
    return ta - tb;
  });

  const labels = sorted.map((p) => formatTimeLabel(p.ts));

  const actualData = sorted.map((p) =>
    p.total_actual != null ? p.total_actual : null,
  );
  const forecastData = sorted.map((p) =>
    p.total_pred != null ? p.total_pred : null,
  );

  const data = {
    labels,
    datasets: [
      {
        label: "実測 合計",
        data: actualData,
        borderColor: "#3B82F6", // 青
        backgroundColor: "rgba(59,130,246,0.15)",
        borderWidth: 2,
        tension: 0.3,
        spanGaps: true,
      },
      {
        label: "予測 合計",
        data: forecastData,
        borderColor: "#F97316", // オレンジ
        backgroundColor: "rgba(249,115,22,0.0)",
        borderWidth: 2,
        borderDash: [6, 4],
        tension: 0.3,
        spanGaps: true,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: "#e5e7eb",
        },
      },
      tooltip: {
        mode: "index" as const,
        intersect: false,
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#9ca3af",
          maxRotation: 0,
          minRotation: 0,
        },
        grid: {
          color: "rgba(148,163,184,0.2)",
        },
      } as const,
      y: {
        beginAtZero: true,
        ticks: {
          color: "#9ca3af",
        },
        grid: {
          color: "rgba(148,163,184,0.2)",
        },
      } as const,
    },
  };

  return (
    <div className="h-64">
      <Line data={data} options={options} />
    </div>
  );
}
