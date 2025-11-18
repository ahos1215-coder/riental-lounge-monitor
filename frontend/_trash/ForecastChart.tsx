"use client";

import { useEffect, useRef } from "react";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
  CategoryScale,
} from "chart.js";
import "chartjs-adapter-date-fns";
import { ja } from "date-fns/locale";

export type ForecastPoint = {
  ts: string;
  men_pred: number;
  women_pred: number;
  total_pred: number;
};

type Props = {
  points: ForecastPoint[];
  title?: string;
};

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
  CategoryScale
);

export default function ForecastChart({ points, title }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;

    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    const data = {
      labels: points.map((p) => p.ts),
      datasets: [
        {
          label: title ?? "合計予測人数（15分刻み）",
          data: points.map((p) => p.total_pred),
          borderWidth: 2,
          tension: 0.3,
          pointRadius: 3,
          pointHoverRadius: 4,
          borderColor: "#3B82F6",
          backgroundColor: "rgba(59,130,246,0.25)",
          fill: true,
        },
      ],
    };

    const chart = new Chart(ctx, {
      type: "line",
      data,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            type: "time",
            time: {
              unit: "minute",
              stepSize: 15,
              displayFormats: { minute: "HH:mm" },
            },
            adapters: {
              date: { locale: ja },
            },
            ticks: {
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 8,
            },
            grid: {
              display: true,
            },
          },
          y: {
            beginAtZero: true,
            ticks: { stepSize: 2 },
          },
        },
        plugins: {
          legend: { display: true, labels: { boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const y = ctx.parsed.y ?? 0;
                return `合計 ${y.toFixed(1)} 人`;
              },
            },
          },
        },
      },
    });

    chartRef.current = chart;

    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, [points, title]);

  return (
    <div className="relative w-full h-72 md:h-80 lg:h-96">
      <canvas ref={canvasRef} />
    </div>
  );
}
