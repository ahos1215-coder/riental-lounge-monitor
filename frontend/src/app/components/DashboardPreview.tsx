"use client";

import { useMemo, useState, useEffect } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  LineChart,
  Line,
} from "recharts";

type TrendPoint = {
  ts: string; // "HH:MM"
  men_actual: number;
  women_actual: number;
  men_pred?: number;
  women_pred?: number;
};

type StoreInfo = {
  id: string;
  name: string;
  distance_km: number;
  open: string;
  close: string;
  is_open: boolean;
  category: "lounge" | "lovehotel" | "ramen";
  rating: number;
  reviews: number;
  extra?: string; // 空室/料金/系統 など
};

type Horizon = "yesterday" | "lastweek" | "custom";

function useDemoData() {
  // 19:00〜05:00 の 2 時間ごとのダミーデータ
  const baseTimes = [
    "19:00",
    "21:00",
    "23:00",
    "01:00",
    "03:00",
    "05:00",
  ];

  const actual: TrendPoint[] = baseTimes.map((ts, idx) => {
    const men = 4 + idx * 3;
    const women = 3 + idx * 2;
    return {
      ts,
      men_actual: men,
      women_actual: women,
      men_pred: men + 2,
      women_pred: women + 1,
    };
  });

  const stores: StoreInfo[] = [
    {
      id: "ol_nagasaki",
      name: "オリエンタルラウンジ 長崎",
      distance_km: 0.2,
      open: "19:00",
      close: "05:00",
      is_open: true,
      category: "lounge",
      rating: 4.3,
      reviews: 128,
      extra: "",
    },
    {
      id: "love_1",
      name: "ラブホ A",
      distance_km: 0.4,
      open: "18:00",
      close: "12:00", // 最遅扱い
      is_open: true,
      category: "lovehotel",
      rating: 4.1,
      reviews: 63,
      extra: "空室 ○ / 休憩¥5,000〜",
    },
    {
      id: "ramen_1",
      name: "ラーメン 太郎",
      distance_km: 0.3,
      open: "18:00",
      close: "02:00",
      is_open: true,
      category: "ramen",
      rating: 4.5,
      reviews: 210,
      extra: "家系ラーメン",
    },
    {
      id: "lounge_2",
      name: "オリエンタルラウンジ 福岡",
      distance_km: 1.5,
      open: "18:00",
      close: "05:00",
      is_open: true,
      category: "lounge",
      rating: 4.0,
      reviews: 95,
    },
    {
      id: "love_2",
      name: "ラブホ B",
      distance_km: 1.0,
      open: "20:00",
      close: "12:00",
      is_open: false,
      category: "lovehotel",
      rating: 3.9,
      reviews: 40,
      extra: "空室 △ / 宿泊¥9,800〜",
    },
    {
      id: "ramen_2",
      name: "ラーメン 一番星",
      distance_km: 0.8,
      open: "11:00",
      close: "23:00",
      is_open: false,
      category: "ramen",
      rating: 4.2,
      reviews: 180,
      extra: "とんこつラーメン",
    },
  ];

  const currentStore = stores[0];

  return { actual, forecast: actual, stores, currentStore };
}

function mergeActualAndForecast(points: TrendPoint[]) {
  return points.map((p) => {
    const total_actual = p.men_actual + p.women_actual;
    const total_pred =
      (p.men_pred ?? p.men_actual) + (p.women_pred ?? p.women_actual);
    return {
      ts: p.ts,
      men_actual: p.men_actual,
      women_actual: p.women_actual,
      men_pred: p.men_pred ?? null,
      women_pred: p.women_pred ?? null,
      total_actual,
      total_pred,
    };
  });
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  const header = Object.keys(rows[0] ?? {});
  const lines = [
    header.join(","),
    ...rows.map((r) =>
      header
        .map((key) => {
          const v = r[key];
          if (v == null) return "";
          const s = String(v).replace(/"/g, '""');
          return `"${s}"`;
        })
        .join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DashboardPreview() {
  const { actual, forecast, stores, currentStore } = useDemoData();
  const [horizon, setHorizon] = useState<Horizon>("yesterday");
  const [showPrevDay, setShowPrevDay] = useState(true);
  const [visibleCount, setVisibleCount] = useState(6);
  const [sortMode, setSortMode] = useState<"distance" | "lateclose">("distance");
  const [feedback, setFeedback] = useState<string | null>(null);

  const merged = useMemo(() => mergeActualAndForecast(actual), [actual]);

  const feedbackKey = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return `megribi_feedback_${currentStore.id}_${today}`;
  }, [currentStore.id]);

  useEffect(() => {
    const saved = window.localStorage.getItem(feedbackKey);
    if (saved) setFeedback(saved);
  }, [feedbackKey]);

  const canFeedback = feedback == null;

  const sortedStores = useMemo(() => {
    const list = [...stores];
    if (sortMode === "distance") {
      list.sort((a, b) => a.distance_km - b.distance_km);
    } else {
      const score = (s: StoreInfo) => {
        const close = s.close;
        if (close === "05:00") return 2;
        if (close === "23:00" || close === "02:00") return 1;
        if (close === "12:00" && s.category === "lovehotel") return 3;
        return 0;
      };
      list.sort((a, b) => score(b) - score(a));
    }
    return list;
  }, [stores, sortMode]);

  const visibleStores = sortedStores.slice(0, visibleCount);

  const totalActualRows = merged.map((p) => ({
    ts: p.ts,
    men_actual: p.men_actual,
    women_actual: p.women_actual,
    total_actual: p.total_actual,
  }));
  const totalForecastRows = merged.map((p) => ({
    ts: p.ts,
    men_pred: p.men_pred,
    women_pred: p.women_pred,
    total_pred: p.total_pred,
  }));

  return (
    <main className="min-h-screen bg-slate-950 text-slate-50 p-4 space-y-6">
      {/* ヘッダー */}
      <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-xl font-bold">
          MEGRIBI ダッシュボード（モック）
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-emerald-700/30 px-3 py-1 text-xs font-semibold text-emerald-200 border border-emerald-500/60">
            現在の店舗: {currentStore.name}
          </span>
          <span className="text-xs text-slate-400">
            表示期間: 19:00 – 05:00（デモデータ）
          </span>
        </div>
      </header>

      {/* 19:00–05:00 男女推移グラフ */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">19:00–05:00 男女推移</h2>
          <div className="flex items-center gap-3 text-xs text-slate-300">
            <label className="flex items-center gap-1">
              範囲:
              <select
                value={horizon}
                onChange={(e) => setHorizon(e.target.value as Horizon)}
                className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
              >
                <option value="yesterday">前日</option>
                <option value="lastweek">先週同曜日</option>
                <option value="custom">指定日</option>
              </select>
            </label>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                className="accent-sky-400"
                checked={showPrevDay}
                onChange={(e) => setShowPrevDay(e.target.checked)}
              />
              前日を重ねて表示（点線）
            </label>
          </div>
        </div>
        <div className="h-64 rounded-xl bg-slate-900 border border-slate-700/70 p-3">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={merged} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="menFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0f172a" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="womenFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f472b6" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0f172a" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" stroke="#9ca3af" />
              <YAxis stroke="#9ca3af" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#020617",
                  borderColor: "#475569",
                  fontSize: "0.75rem",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="men_actual"
                name="男性（実測）"
                stroke="#38bdf8"
                fill="url(#menFill)"
                fillOpacity={0.6}
              />
              <Area
                type="monotone"
                dataKey="women_actual"
                name="女性（実測）"
                stroke="#f472b6"
                fill="url(#womenFill)"
                fillOpacity={0.6}
              />
              {showPrevDay && (
                <>
                  <Line
                    type="monotone"
                    dataKey="men_pred"
                    name="男性（予測・前日相当）"
                    stroke="#38bdf8"
                    strokeDasharray="4 4"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="women_pred"
                    name="女性（予測・前日相当）"
                    stroke="#f472b6"
                    strokeDasharray="4 4"
                    dot={false}
                  />
                </>
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* 今日の混み具合の推移（実測＋予測） */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          今日の混み具合の推移（実測＋予測）
        </h2>
        <div className="h-64 rounded-xl bg-slate-900 border border-slate-700/70 p-3">
          {merged.length === 0 ? (
            <p className="text-sm text-slate-400">データがありません。</p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="ts" stroke="#9ca3af" />
                <YAxis stroke="#9ca3af" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#020617",
                    borderColor: "#475569",
                    fontSize: "0.75rem",
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="total_actual"
                  name="合計（実測）"
                  stroke="#facc15"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="total_pred"
                  name="合計（予測）"
                  stroke="#f97316"
                  strokeDasharray="4 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <button
            type="button"
            onClick={() =>
              totalActualRows.length &&
              downloadCsv("actual_demo.csv", totalActualRows)
            }
            className="rounded-md border border-slate-600 px-3 py-1 hover:bg-slate-800"
          >
            実測CSVをダウンロード
          </button>
          <button
            type="button"
            onClick={() =>
              totalForecastRows.length &&
              downloadCsv("forecast_demo.csv", totalForecastRows)
            }
            className="rounded-md border border-slate-600 px-3 py-1 hover:bg-slate-800"
          >
            予測CSVをダウンロード
          </button>
        </div>
      </section>

      {/* 近くのお店セクション */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">近くのお店（サンプル）</h2>
          <div className="flex items-center gap-3 text-xs text-slate-300">
            <label className="flex items-center gap-1">
              並び替え:
              <select
                value={sortMode}
                onChange={(e) =>
                  setSortMode(e.target.value as "distance" | "lateclose")
                }
                className="rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
              >
                <option value="distance">距離が近い順</option>
                <option value="lateclose">閉店が遅い順</option>
              </select>
            </label>
          </div>
        </div>
        <div className="space-y-2">
          {visibleStores.map((s) => (
            <div
              key={s.id}
              className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm flex flex-col gap-1"
            >
              <div className="flex items-center justify-between">
                <div className="font-semibold">{s.name}</div>
                <div className="text-xs text-slate-400">
                  {s.distance_km.toFixed(1)} km
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                <span>
                  営業時間: {s.open}〜{s.close}
                </span>
                <span
                  className={
                    "inline-flex items-center rounded-full px-2 py-0.5 border text-[10px] " +
                    (s.is_open
                      ? "border-emerald-500 text-emerald-200"
                      : "border-slate-500 text-slate-300")
                  }
                >
                  {s.is_open ? "営業中" : "営業時間外"}
                </span>
                <span>
                  ★ {s.rating.toFixed(1)}（{s.reviews}件）
                </span>
                {s.category === "lovehotel" && s.extra && (
                  <span className="text-pink-300">{s.extra}</span>
                )}
                {s.category === "ramen" && s.extra && (
                  <span className="text-amber-300">系統: {s.extra}</span>
                )}
              </div>
            </div>
          ))}
        </div>
        {visibleCount < sortedStores.length && (
          <button
            type="button"
            onClick={() =>
              setVisibleCount((prev) =>
                Math.min(prev + 6, sortedStores.length),
              )
            }
            className="mt-2 rounded-md border border-slate-600 px-4 py-1 text-xs hover:bg-slate-800"
          >
            もっと見る（+6）
          </button>
        )}
      </section>

      {/* フィードバック */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">今日の結果フィードバック</h2>
        <p className="text-xs text-slate-300">
          1日1回だけ、同じブラウザからのフィードバックが記録されます（デモ）。
        </p>
        <div className="flex flex-wrap gap-2 text-xs">
          {[
            "お持ち帰りできた",
            "お持ち帰りできなかった",
            "役に立った",
            "クソの役にも立たなかった",
          ].map((label) => (
            <button
              key={label}
              type="button"
              onClick={() => {
                if (!canFeedback) {
                  alert("今日はすでにフィードバック済みです（デモ）。");
                  return;
                }
                window.localStorage.setItem(feedbackKey, label);
                setFeedback(label);
              }}
              className={
                "rounded-full border px-4 py-1 " +
                (feedback === label
                  ? "border-emerald-500 bg-emerald-500/20 text-emerald-100"
                  : "border-slate-600 hover:bg-slate-800")
              }
            >
              {label}
            </button>
          ))}
        </div>
        {feedback && (
          <p className="text-xs text-emerald-300">
            今日のフィードバック: {feedback}
          </p>
        )}
      </section>

      {/* 店舗一覧（簡易） */}
      <section className="space-y-2 pb-8">
        <h2 className="text-lg font-semibold">オリエンタルラウンジ 店舗一覧（静的）</h2>
        <p className="text-xs text-slate-400">
          本番では /api/stores/list に差し替え予定。
        </p>
        <div className="text-xs text-slate-300 flex flex-wrap gap-2">
          {["長崎", "福岡", "渋谷", "新宿", "梅田", "名古屋"].map((name) => (
            <span
              key={name}
              className="rounded-full border border-slate-600 px-3 py-1"
            >
              オリエンタルラウンジ {name}
            </span>
          ))}
        </div>
      </section>
    </main>
  );
}
