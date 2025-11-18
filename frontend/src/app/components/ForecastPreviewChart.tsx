"use client";

import { useRef, useEffect } from "react";
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
import type { ForecastPoint } from "./ForecastChart";

type Props = {
  points: ForecastPoint[];
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

export default function ForecastPreviewChart({ points }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;

    // 既存チャートがあれば破棄
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    const labels = points.map((p) => new Date(p.ts));

    const data = {
      labels,
      datasets: [
        {
          label: "女性（予測）",
          data: points.map((p) => p.women_pred),
          borderWidth: 2,
          tension: 0.3,
          pointRadius: 0,
          fill: false,
        },
        {
          label: "男性（予測）",
          data: points.map((p) => p.men_pred),
          borderWidth: 2,
          borderDash: [4, 4],
          tension: 0.3,
          pointRadius: 0,
          fill: false,
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
              unit: "hour",
              displayFormats: { hour: "HH:mm" },
            } as any,
            adapters: {
              date: { locale: ja },
            },
            ticks: {
              maxRotation: 0,
              autoSkip: true,
            },
            grid: {
              display: true,
            },
          },
          y: {
            beginAtZero: true,
            ticks: {
              stepSize: 5,
            },
          },
        },
        plugins: {
          legend: {
            display: true,
            labels: { boxWidth: 12 },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const y = ctx.parsed.y ?? 0;
                const label = ctx.dataset.label ?? "";
                return `${label}: ${y.toFixed(1)} 人`;
              },
            },
          },
        },
      },
    });

    chartRef.current = chart;

    // クリーンアップ
    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, [points]);

  return (
    <div className="relative w-full h-72 md:h-80 lg:h-96">
      <canvas ref={canvasRef} />
    </div>
  );
}
