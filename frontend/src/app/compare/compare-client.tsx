"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  STORES,
  STORE_REGION_FILTER_ORDER,
  type StoreMeta,
} from "@/app/config/stores";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const MAX_COMPARE = 3;

type RangeRow = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

type ForecastRow = {
  ts?: string;
  total_pred?: number;
};

type StoreData = {
  slug: string;
  label: string;
  areaLabel: string;
  menCount: number;
  womenCount: number;
  total: number;
  genderRatio: string;
  sparkline: { ts: number; total: number }[];
  forecast: { ts: number; total: number }[];
  megribiScore: number | null;
  loading: boolean;
};

const COLORS = ["#818cf8", "#f472b6", "#34d399"];

function formatTime(ts: number): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("ja-JP", {
      timeZone: "Asia/Tokyo",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return "";
  }
}

function genderRatioLabel(men: number, women: number): string {
  const total = men + women;
  if (total === 0) return "-";
  const wPct = Math.round((women / total) * 100);
  return `${wPct}%`;
}

function scoreLabel(score: number | null): { text: string; className: string } {
  if (score == null) return { text: "-", className: "text-white/40" };
  if (score >= 0.65) return { text: "狙い目", className: "text-emerald-300" };
  if (score >= 0.4) return { text: "様子見", className: "text-amber-300" };
  return { text: "他店へ", className: "text-red-300" };
}

export default function CompareClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>([]);
  const [storeDataMap, setStoreDataMap] = useState<Record<string, StoreData>>({});
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [searchText, setSearchText] = useState("");

  // Initialize from URL params
  useEffect(() => {
    const s = searchParams.get("stores");
    if (s) {
      const slugs = s.split(",").filter((sl) => STORES.some((st) => st.slug === sl)).slice(0, MAX_COMPARE);
      setSelectedSlugs(slugs);
    }
  }, [searchParams]);

  // Sync URL
  const updateUrl = useCallback(
    (slugs: string[]) => {
      const params = new URLSearchParams();
      if (slugs.length > 0) params.set("stores", slugs.join(","));
      router.replace(`/compare?${params.toString()}`, { scroll: false });
    },
    [router],
  );

  const addStore = useCallback(
    (slug: string) => {
      setSelectedSlugs((prev) => {
        if (prev.includes(slug) || prev.length >= MAX_COMPARE) return prev;
        const next = [...prev, slug];
        updateUrl(next);
        return next;
      });
      setSelectorOpen(false);
      setSearchText("");
    },
    [updateUrl],
  );

  const removeStore = useCallback(
    (slug: string) => {
      setSelectedSlugs((prev) => {
        const next = prev.filter((s) => s !== slug);
        updateUrl(next);
        return next;
      });
      setStoreDataMap((prev) => {
        const copy = { ...prev };
        delete copy[slug];
        return copy;
      });
    },
    [updateUrl],
  );

  // Fetch data for selected stores
  useEffect(() => {
    if (selectedSlugs.length === 0) return;

    const slugsToFetch = selectedSlugs.filter((s) => !storeDataMap[s] || storeDataMap[s].loading);
    if (slugsToFetch.length === 0) return;

    // Mark as loading
    setStoreDataMap((prev) => {
      const copy = { ...prev };
      for (const slug of slugsToFetch) {
        const meta = STORES.find((s) => s.slug === slug);
        copy[slug] = {
          slug,
          label: meta?.label ?? slug,
          areaLabel: meta?.areaLabel ?? "",
          menCount: 0,
          womenCount: 0,
          total: 0,
          genderRatio: "-",
          sparkline: [],
          forecast: [],
          megribiScore: null,
          loading: true,
        };
      }
      return copy;
    });

    const csvSlugs = selectedSlugs.join(",");

    // Fetch range_multi + megribi_score + forecast in parallel
    Promise.all([
      fetch(`/api/range_multi?stores=${csvSlugs}&limit=200`).then((r) => r.json()).catch(() => ({})),
      fetch(`/api/megribi_score?stores=${csvSlugs}`).then((r) => r.json()).catch(() => ({})),
      fetch(`/api/forecast_today_multi?stores=${csvSlugs}`).then((r) => r.json()).catch(() => ({})),
    ]).then(([rangeData, scoreData, forecastData]) => {
      setStoreDataMap((prev) => {
        const copy = { ...prev };
        for (const slug of selectedSlugs) {
          const meta = STORES.find((s) => s.slug === slug);
          const rows: RangeRow[] = Array.isArray(rangeData?.[slug]) ? rangeData[slug] : [];
          const latest = rows[rows.length - 1];
          const men = latest?.men ?? 0;
          const women = latest?.women ?? 0;

          const sparkline = rows
            .filter((r): r is RangeRow & { ts: string } => Boolean(r.ts))
            .map((r) => ({ ts: new Date(r.ts!).getTime(), total: (r.men ?? 0) + (r.women ?? 0) }));

          const forecastRows: ForecastRow[] = Array.isArray(forecastData?.[slug]) ? forecastData[slug] : [];
          const forecastPoints = forecastRows
            .filter((r): r is ForecastRow & { ts: string } => Boolean(r.ts))
            .map((r) => ({ ts: new Date(r.ts!).getTime(), total: r.total_pred ?? 0 }));

          const score = typeof scoreData?.[slug]?.megribi_score === "number" ? scoreData[slug].megribi_score : null;

          copy[slug] = {
            slug,
            label: meta?.label ?? slug,
            areaLabel: meta?.areaLabel ?? "",
            menCount: men,
            womenCount: women,
            total: men + women,
            genderRatio: genderRatioLabel(men, women),
            sparkline,
            forecast: forecastPoints,
            megribiScore: score,
            loading: false,
          };
        }
        return copy;
      });
    });
  }, [selectedSlugs]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build merged chart data
  const chartData = useMemo(() => {
    const allTsSet = new Set<number>();
    for (const slug of selectedSlugs) {
      const data = storeDataMap[slug];
      if (!data) continue;
      for (const p of data.sparkline) allTsSet.add(p.ts);
      for (const p of data.forecast) allTsSet.add(p.ts);
    }
    const allTs = Array.from(allTsSet).sort((a, b) => a - b);

    return allTs.map((ts) => {
      const point: Record<string, unknown> = { ts, label: formatTime(ts) };
      for (const slug of selectedSlugs) {
        const data = storeDataMap[slug];
        if (!data) continue;
        const actual = data.sparkline.find((p) => p.ts === ts);
        const fc = data.forecast.find((p) => p.ts === ts);
        if (actual) point[`actual_${slug}`] = actual.total;
        if (fc) point[`forecast_${slug}`] = fc.total;
      }
      return point;
    });
  }, [selectedSlugs, storeDataMap]);

  const filteredStores = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    return STORES.filter(
      (s) =>
        !selectedSlugs.includes(s.slug) &&
        (q === "" || s.label.toLowerCase().includes(q) || s.slug.includes(q) || s.areaLabel.toLowerCase().includes(q)),
    );
  }, [searchText, selectedSlugs]);

  const regionGroups = useMemo(() => {
    const groups: Record<string, StoreMeta[]> = {};
    for (const s of filteredStores) {
      (groups[s.regionLabel] ??= []).push(s);
    }
    return STORE_REGION_FILTER_ORDER
      .filter((r) => groups[r]?.length)
      .map((r) => ({ region: r, stores: groups[r] }));
  }, [filteredStores]);

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
      <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
        <div className="mb-4">
          <Link href="/stores" className="text-sm text-white/50 hover:text-white">
            ← 店舗一覧に戻る
          </Link>
        </div>

        <h1 className="text-2xl font-black tracking-tight md:text-3xl">店舗比較</h1>
        <p className="mt-2 text-sm text-white/60">
          最大{MAX_COMPARE}店舗を並べてリアルタイム混雑を比較できます。
        </p>

        {/* Store selector */}
        <div className="mt-6 flex flex-wrap items-center gap-3">
          {selectedSlugs.map((slug, i) => {
            const data = storeDataMap[slug];
            return (
              <span
                key={slug}
                className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-4 py-2 text-sm"
              >
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: COLORS[i] }}
                />
                {data?.label ?? slug}
                <button
                  onClick={() => removeStore(slug)}
                  className="ml-1 text-white/40 hover:text-white"
                  aria-label={`${data?.label ?? slug} を削除`}
                >
                  ×
                </button>
              </span>
            );
          })}
          {selectedSlugs.length < MAX_COMPARE && (
            <button
              onClick={() => setSelectorOpen(true)}
              className="rounded-full border border-dashed border-white/20 px-4 py-2 text-sm text-white/50 hover:border-indigo-400/40 hover:text-white"
            >
              + 店舗を追加
            </button>
          )}
        </div>

        {/* Store picker modal */}
        {selectorOpen && (
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between gap-4">
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="店舗名・エリアで検索..."
                className="flex-1 rounded-xl border border-white/10 bg-black/50 px-4 py-2 text-sm text-white placeholder:text-white/30 focus:border-indigo-500/50 focus:outline-none"
                autoFocus
              />
              <button
                onClick={() => { setSelectorOpen(false); setSearchText(""); }}
                className="text-sm text-white/40 hover:text-white"
              >
                閉じる
              </button>
            </div>
            <div className="mt-3 max-h-64 overflow-y-auto">
              {regionGroups.map(({ region, stores }) => (
                <div key={region} className="mb-3">
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    {region}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {stores.map((s) => (
                      <button
                        key={s.slug}
                        onClick={() => addStore(s.slug)}
                        className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/80 hover:border-indigo-400/30 hover:bg-white/[0.07]"
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Comparison cards */}
        {selectedSlugs.length > 0 && (
          <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {selectedSlugs.map((slug, i) => {
              const data = storeDataMap[slug];
              if (!data) return null;
              const sc = scoreLabel(data.megribiScore);
              return (
                <div
                  key={slug}
                  className="rounded-2xl border border-white/10 bg-white/5 p-5"
                  style={{ borderTopColor: COLORS[i], borderTopWidth: "3px" }}
                >
                  {data.loading ? (
                    <div className="space-y-3">
                      <div className="h-4 w-32 animate-pulse rounded bg-white/10" />
                      <div className="h-8 w-20 animate-pulse rounded bg-white/10" />
                    </div>
                  ) : (
                    <>
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="text-lg font-bold">{data.label}</p>
                          <p className="text-[11px] text-white/40">{data.areaLabel}</p>
                        </div>
                        <span className={`text-sm font-bold ${sc.className}`}>{sc.text}</span>
                      </div>
                      <div className="mt-4 grid grid-cols-3 gap-3 text-center">
                        <div>
                          <p className="text-[10px] text-white/50">合計</p>
                          <p className="text-xl font-black">{data.total}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-white/50">男性</p>
                          <p className="text-xl font-black text-blue-300">{data.menCount}</p>
                        </div>
                        <div>
                          <p className="text-[10px] text-white/50">女性</p>
                          <p className="text-xl font-black text-pink-300">{data.womenCount}</p>
                        </div>
                      </div>
                      <div className="mt-3 flex items-center justify-between text-xs text-white/50">
                        <span>女性比率: {data.genderRatio}</span>
                        <Link
                          href={`/store/${slug}?store=${slug}`}
                          className="text-indigo-300/80 hover:text-indigo-200"
                        >
                          詳細 →
                        </Link>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Merged chart */}
        {selectedSlugs.length >= 2 && chartData.length > 0 && (
          <section className="mt-8 rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
            <h2 className="text-lg font-bold">混雑推移の比較</h2>
            <p className="mt-1 text-xs text-white/50">
              実線 = 実測、点線 = ML 予測
            </p>
            <div className="mt-4 h-72 w-full min-w-0">
              <ResponsiveContainer width="100%" height={288}>
                <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                  <XAxis
                    type="number"
                    dataKey="ts"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={(v) => formatTime(v)}
                    stroke="#94a3b8"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                  />
                  <YAxis
                    stroke="#94a3b8"
                    tick={{ fill: "#94a3b8", fontSize: 10 }}
                    label={{ value: "人", angle: 0, position: "insideTopLeft", fill: "#64748b", fontSize: 10 }}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                    labelFormatter={(_, payload) => {
                      const row = payload?.[0]?.payload as { label?: string } | undefined;
                      return row?.label ?? "";
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {selectedSlugs.map((slug, i) => {
                    const data = storeDataMap[slug];
                    const name = data?.label ?? slug;
                    return [
                      <Line
                        key={`actual_${slug}`}
                        type="monotone"
                        dataKey={`actual_${slug}`}
                        name={`${name}（実測）`}
                        stroke={COLORS[i]}
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                        connectNulls={false}
                      />,
                      <Line
                        key={`forecast_${slug}`}
                        type="monotone"
                        dataKey={`forecast_${slug}`}
                        name={`${name}（予測）`}
                        stroke={COLORS[i]}
                        strokeWidth={1.5}
                        strokeDasharray="6 3"
                        dot={false}
                        isAnimationActive={false}
                        connectNulls={false}
                      />,
                    ];
                  })}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {selectedSlugs.length === 0 && (
          <div className="mt-12 rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-8 text-center">
            <p className="text-lg font-bold text-white/70">店舗を選択してください</p>
            <p className="mt-2 text-sm text-white/40">
              「+ 店舗を追加」ボタンから最大{MAX_COMPARE}店舗を選んで比較できます。
            </p>
            <button
              onClick={() => setSelectorOpen(true)}
              className="mt-4 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-6 py-2.5 text-sm font-semibold text-indigo-200 hover:border-indigo-400/50 hover:bg-indigo-500/15"
            >
              店舗を追加
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
