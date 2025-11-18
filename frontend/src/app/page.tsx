"use client";

import { useEffect, useState } from "react";
import { ForecastNextHourChart, ForecastPoint } from "./components/ForecastNextHourChart";
import { DebugSection } from "./components/DebugSection";

async function fetchForecastNextHour(): Promise<ForecastPoint[]> {
  const url = "/api/forecast_next_hour?store=nagasaki";
  const res = await fetch(url);

  if (!res.ok) {
    throw new Error("HTTP error: " + res.status);
  }

  const json = await res.json();

  if (!json || json.ok !== true || !Array.isArray(json.data)) {
    throw new Error("Unexpected response for next_hour");
  }

  return json.data as ForecastPoint[];
}

async function fetchForecastToday(): Promise<ForecastPoint[]> {
  const url = "/api/forecast_today?store=nagasaki";
  const res = await fetch(url);

  if (!res.ok) {
    throw new Error("HTTP error: " + res.status);
  }

  const json = await res.json();

  if (!json || json.ok !== true || !Array.isArray(json.data)) {
    throw new Error("Unexpected response for forecast_today");
  }

  return json.data as ForecastPoint[];
}

export default function Page() {
  const [nextHourRows, setNextHourRows] = useState<ForecastPoint[]>([]);
  const [todayRows, setTodayRows] = useState<ForecastPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const [nextHour, today] = await Promise.all([
          fetchForecastNextHour(),
          fetchForecastToday(),
        ]);

        if (cancelled) return;

        setNextHourRows(nextHour);
        setTodayRows(today);
      } catch (e) {
        console.error(e);
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "予測データの取得中に不明なエラーが発生しました。"
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="p-6 space-y-8">
      <section>
        <h1 className="text-2xl font-bold mb-4">
          長崎店：15分間隔 予測グラフ
        </h1>

        <div className="mb-4 flex items-center gap-4">
          {loading && (
            <p className="text-sm text-slate-500">読み込み中...</p>
          )}
          {error && (
            <p className="text-red-500 text-sm">
              {error}
            </p>
          )}
          <button
            type="button"
            onClick={() => setShowDebug((v) => !v)}
            className="ml-auto rounded border px-3 py-1 text-xs hover:bg-slate-100"
          >
            {showDebug ? "デバッグ情報を隠す" : "デバッグ情報を表示"}
          </button>
        </div>

        <ForecastNextHourChart points={nextHourRows} />
      </section>

      <DebugSection
        title="生データ（next_hour / デバッグ用）"
        json={nextHourRows}
        visible={showDebug}
      />

      <DebugSection
        title="今日の予測データ（forecast_today / デバッグ用）"
        json={todayRows}
        visible={showDebug}
      />
    </main>
  );
}
