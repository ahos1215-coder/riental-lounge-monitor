"use client";

import React, {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ForecastNextHourChart,
  type ForecastPoint,
} from "./components/ForecastNextHourChart";
import ForecastPreviewChart from "./components/ForecastPreviewChart";
import { DebugSection } from "./components/DebugSection";
import type { RangeRow } from "./types/range";
import {
  DEFAULT_STORE,
  STORE_OPTIONS,
  type StoreOption,
} from "./config/stores";

// 直近1時間の予測を取得
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
    throw new Error("Unexpected response for forecast_next_hour");
  }
  return json.data as ForecastPoint[];
}

// 今日1日の予測を取得
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

// 直近の実測レンジを取得（天気付き）
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
  const [loading, setLoading] = useState(false);
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
    STORE_OPTIONS.find((opt: StoreOption) => opt.value === storeSlug)?.label ??
    storeSlug;

  const handleStoreChange = (e: ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    const qp = new URLSearchParams(searchParams?.toString() ?? "");
    qp.set("store", value);
    router.push(`/?${qp.toString()}`);
  };

  const toggleDebug = () => {
    setShowDebug((v: boolean) => !v);
  };

  return (
    <main className="p-6 space-y-8">
      {/* Section1: 今から1時間の予測 + 現在状況 + 天気 */}
      <section className="space-y-4">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold">
            {currentStoreLabel}：15分間隔 予測グラフ
          </h1>

          <label className="text-sm text-slate-600 flex items-center gap-2">
            店舗:
            <select
              className="rounded border px-2 py-1 text-sm"
              value={storeSlug}
              onChange={handleStoreChange}
            >
              {STORE_OPTIONS.map((opt: StoreOption) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <div className="ml-auto flex items-center gap-3">
            {loading && (
              <p className="text-sm text-slate-500">読み込み中...</p>
            )}
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <button
              type="button"
              onClick={toggleDebug}
              className="rounded border px-3 py-1 text-xs hover:bg-slate-100"
            >
              {showDebug ? "デバッグを隠す" : "デバッグを表示"}
            </button>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2 rounded border border-slate-200 bg-white p-3 shadow-sm">
            <ForecastNextHourChart points={nextHourRows} />
          </div>
          <div className="space-y-3">
            <CurrentStatusCard
              rangeRows={rangeRows}
              nextHourRows={nextHourRows}
            />
            <WeatherSummary rows={rangeRows} />
          </div>
        </div>
      </section>

      {/* Section2: 今日全体の予測推移 */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">今日の混み具合の予測推移</h2>
        <div className="rounded border border-slate-200 bg-white p-3 shadow-sm">
          <ForecastPreviewChart points={todayRows} />
        </div>
      </section>

      {/* デバッグ表示 */}
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
      <DebugSection
        title="直近レンジデータ（/api/range / デバッグ用）"
        json={rangeRows}
        visible={showDebug}
      />
    </main>
  );
}

// 現在の状況カード
function CurrentStatusCard(props: {
  rangeRows: RangeRow[];
  nextHourRows: ForecastPoint[];
}) {
  const { rangeRows, nextHourRows } = props;

  if (!rangeRows || rangeRows.length === 0) return null;

  const latest = rangeRows[rangeRows.length - 1];
  const men = latest.men ?? 0;
  const women = latest.women ?? 0;
  const total = latest.total ?? men + women;

  const ts = latest.ts ? new Date(latest.ts) : null;
  const hhmm =
    ts != null
      ? new Intl.DateTimeFormat("ja-JP", {
          hour: "2-digit",
          minute: "2-digit",
        }).format(ts)
      : "-";

  const peakNextHour =
    nextHourRows && nextHourRows.length > 0
      ? Math.max(...nextHourRows.map((p) => p.total_pred ?? 0))
      : null;

  return (
    <div className="rounded border border-slate-200 bg-white p-3 text-sm text-slate-800 shadow-sm">
      <p className="font-semibold mb-2">現在の状況</p>
      <p className="text-xs text-slate-500 mb-1">時刻: {hhmm}</p>
      <p>男性: {men} 人</p>
      <p>女性: {women} 人</p>
      <p className="font-semibold">合計: {total} 人</p>
      {peakNextHour != null && (
        <p className="text-xs text-slate-500 mt-2">
          今後1時間のピーク予測: 約 {peakNextHour.toFixed(0)} 人
        </p>
      )}
    </div>
  );
}

// 直近の天気サマリー
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
    <div className="rounded border border-slate-200 bg-white p-3 text-sm text-slate-700 shadow-sm">
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
