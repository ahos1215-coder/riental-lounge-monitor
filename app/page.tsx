"use client";

import { useEffect, useState } from "react";
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

ChartJS.register(LineElement, CategoryScale, LinearScale, PointElement, Tooltip, Legend);

export default function Page() {
  const [data, setData] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/forecast")
      .then((res) => res.json())
      .then((json) => setData(json.data || []))
      .catch((err) => setError(String(err)));
  }, []);

  const chartData = {
    labels: data.map((d: any) =>
      new Date(d.ts).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })
    ),
    datasets: [
      { label: "p50（中央値）", data: data.map((d: any) => d.total_p50), borderColor: "#3B82F6", tension: 0.3 },
      { label: "p10（下限）", data: data.map((d: any) => d.total_p10), borderColor: "rgba(59,130,246,0.3)", borderDash: [5, 5], tension: 0.3 },
      { label: "p90（上限）", data: data.map((d: any) => d.total_p90), borderColor: "rgba(59,130,246,0.3)", borderDash: [5, 5], tension: 0.3 },
    ],
  };

  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold mb-4">長崎店 予測ダッシュボード</h1>
      {error && <p className="text-red-500">{error}</p>}
      <div className="bg-white rounded-xl shadow p-4">
        <Line data={chartData} />
      </div>
    </main>
  );
}
