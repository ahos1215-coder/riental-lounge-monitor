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

export type TodayPoint = {
  ts: string;
  men: number;
  women: number;
};

type Props = {
  points: TodayPoint[];
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

export default function TodayChart({ points, title }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;

    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    const chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: points.map((p) => p.ts),
        datasets: [
          {
            label: "男性",
            data: points.map((p) => p.men),
            borderColor: "#3B82F6",
            backgroundColor: "rgba(59,130,246,0.2)",
            pointRadius: 3,
            borderWidth: 2,
            tension: 0.3,
          },
          {
            label: "女性",
            data: points.map((p) => p.women),
            borderColor: "#EC4899",
            backgroundColor: "rgba(236,72,153,0.2)",
            pointRadius: 3,
            borderWidth: 2,
            tension: 0.3,
          },
        ],
      },
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
            },
            adapters: { date: { locale: ja } },
            ticks: { maxTicksLimit: 12 },
          },
          y: {
            beginAtZero: true,
            ticks: { stepSize: 5 },
          },
        },
        plugins: {
          legend: { labels: { boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (ctx) =>
                `${ctx.dataset.label}: ${ctx.parsed.y}人`,
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
  }, [points]);

  return (
    <div className="relative w-full h-80 md:h-96">
      <canvas ref={canvasRef} />
    </div>
  );
}
