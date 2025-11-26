"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ForecastNextHourChart,
  ForecastPoint,
} from "./components/ForecastNextHourChart";
import { DebugSection } from "./components/DebugSection";
import { RangeRow } from "./types/range";
import { DEFAULT_STORE, STORE_OPTIONS } from "./config/stores";

async function fetchForecastNextHour(
  storeSlug: string,
): Promise<ForecastPoint[]> {
  const url = `/api/forecast_next_hour?store=${encodeURIComponent(storeSlug)}`;
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

async function fetchForecastToday(storeSlug: string): Promise<ForecastPoint[]> {
  const url = `/api/forecast_today?store=${encodeURIComponent(storeSlug)}`;
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

async function fetchRecentRange(storeSlug: string): Promise<RangeRow[]> {
  const url = `/api/range?limit=24&store=${encodeURIComponent(storeSlug)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error("HTTP error: " + res.status);
  }
  const json = await res.json();
  if (!json || json.ok !== true || !Array.isArray(json.rows)) {
    throw new Error("Unexpected response for range");
  }
  return json.rows as RangeRow[];
}

export default function Page() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const storeSlug = useMemo(() => {
    const raw = searchParams?.get("store")?.trim();
    return raw || DEFAULT_STORE;
  }, [searchParams]);

  const [nextHourRows, setNextHourRows] = useState<ForecastPoint[]>([]);
  const [todayRows, setTodayRows] = useState<ForecastPoint[]>([]);
  const [rangeRows, setRangeRows] = useState<RangeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);
        const [nextHour, today, recentRange] = await Promise.all([
          fetchForecastNextHour(storeSlug),
          fetchForecastToday(storeSlug),
          fetchRecentRange(storeSlug),
        ]);
        if (cancelled) return;
        setNextHourRows(nextHour);
        setTodayRows(today);
        setRangeRows(recentRange);
      } catch (e) {
        console.error(e);
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "データの取得中にエラーが発生しました。",
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
  }, [storeSlug]);

  const currentStoreLabel =
    STORE_OPTIONS.find((opt) => opt.value === storeSlug)?.label ?? storeSlug;

  return (
    <main className="p-6 space-y-8">
      <section>
        <div className="flex items-center gap-4 mb-4">
          <h1 className="text-2xl font-bold">
            {currentStoreLabel}：15分間隔 予測グラフ
          </h1>
          <label className="text-sm text-slate-600">
            店舗:
            <select
              className="ml-2 rounded border px-2 py-1 text-sm"
              value={storeSlug}
              onChange={(e) => {
                const value = e.target.value;
                const qp = new URLSearchParams(
                  searchParams?.toString() ?? "",
                );
                qp.set("store", value);
                router.push(`/?${qp.toString()}`);
              }}
            >
              {STORE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mb-4 flex items-center gap-4">
          {loading && (
            <p className="text-sm text-slate-500">読み込み中...</p>
          )}
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <button
            type="button"
            onClick={() => setShowDebug((v) => !v)}
            className="ml-auto rounded border px-3 py-1 text-xs hover:bg-slate-100"
          >
            {showDebug ? "デバッグを隠す" : "デバッグを表示"}
          </button>
        </div>

        <ForecastNextHourChart points={nextHourRows} />
        <WeatherSummary rows={rangeRows} />
      </section>

      <DebugSection
        title="予測データ（next_hour / デバッグ用）"
        json={nextHourRows}
        visible={showDebug}
      />
      <DebugSection
        title="本日の予測データ（forecast_today / デバッグ用）"
        json={todayRows}
        visible={showDebug}
      />
    </main>
  );
}

function WeatherSummary({ rows }: { rows: RangeRow[] }) {
  if (!rows || rows.length === 0) return null;

  const latest = rows[rows.length - 1];
  const label = latest.weather_label ?? "天気情報なし";
  const temp =
    latest.temp_c != null ? `${latest.temp_c.toFixed(1)}℃` : null;
  const precip =
    latest.precip_mm != null
      ? `降水 ${latest.precip_mm.toFixed(1)}mm`
      : null;

  return (
    <div className="mt-4 rounded border border-slate-200 bg-white p-3 text-sm text-slate-700 shadow-sm">
      <p className="font-semibold mb-1">直近の天気</p>
      <p>
        {label}
        {temp ? ` / ${temp}` : ""}
        {precip ? ` / ${precip}` : ""}
      </p>
      <p className="text-xs text-slate-500 mt-1">
        ※ /api/range の weather_* を利用
      </p>
    </div>
  );
}
