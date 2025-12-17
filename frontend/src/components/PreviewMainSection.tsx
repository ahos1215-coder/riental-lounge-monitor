"use client";

import { useEffect, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";

import SecondVenuesList from "./SecondVenuesList";
import type {
  PreviewRangeMode,
  StoreSnapshot,
} from "../app/hooks/useStorePreviewData";

const cardClass = "rounded-3xl border border-slate-800 bg-slate-950/80";

const RANGE_MODE_OPTIONS: { id: PreviewRangeMode; label: string }[] = [
  { id: "today", label: "今日" },
  { id: "yesterday", label: "昨日" },
  { id: "lastWeek", label: "先週" },
  { id: "custom", label: "カスタム" },
];

type TimelinePayloadEntry = {
  name?: string;
  value?: number | null;
  color?: string;
};

type TimelineTooltipProps = TooltipProps<number, string> & {
  label?: string | number;
  payload?: TimelinePayloadEntry[];
};

function TimelineTooltip({ active, payload, label = "" }: TimelineTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const filtered = payload.filter((entry) => {
    const name = entry.name ?? "";
    return name !== "menActual" && name !== "womenActual";
  });

  if (filtered.length === 0) return null;

  return (
    <div
      style={{
        backgroundColor: "#020617",
        border: "1px solid #1f2937",
        borderRadius: 8,
        fontSize: 11,
        padding: "6px 8px",
      }}
    >
      <p style={{ marginBottom: 4, color: "#e5e7eb" }}>{label}</p>

      {filtered.map((entry, idx) => {
        const name = entry.name ?? "";
        const raw = entry.value;

        let valueText = "-";
        if (typeof raw === "number") {
          valueText = name.includes("予測")
            ? raw.toFixed(1)
            : Math.round(raw).toString();
        }

        const color = entry.color ?? "#e5e7eb";

        return (
          <p key={`${name}-${idx}`} style={{ color }}>
            {name}: {valueText}
          </p>
        );
      })}
    </div>
  );
}

type PreviewMainSectionProps = {
  storeSlug: string;
  snapshot: StoreSnapshot;
  loading?: boolean;
  error?: string | null;
  onSelectStore?: (slug: string) => void;
  rangeMode?: PreviewRangeMode;
  onChangeRangeMode?: (mode: PreviewRangeMode) => void;
  customDate?: string;
  onChangeCustomDate?: (value: string) => void;
  selectedBaseDate?: string;
};

export default function PreviewMainSection(props: PreviewMainSectionProps) {
  const {
    storeSlug,
    snapshot,
    loading,
    error,
    rangeMode,
    onChangeRangeMode,
    customDate = "",
    onChangeCustomDate,
    selectedBaseDate,
  } = props;
  const hasData = snapshot.hasData;
  const activeRangeMode = rangeMode ?? "today";
  const canControlRange = typeof onChangeRangeMode === "function";

  
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  const openDatePicker = () => {
    const el =
      dateInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!el) return;
    el.focus();
    el.showPicker?.();
  };
const [isClient, setIsClient] = useState(false);
  useEffect(() => setIsClient(true), []);

  return (
    <div className="flex w-full min-w-0 flex-col gap-6">
      <section className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5 text-xs">
            <p className="text-[11px] text-slate-400">今見ている店舗</p>
            <p className="text-sm font-semibold text-slate-100">
              {snapshot.area} / {snapshot.name}
            </p>
            <p className="text-[11px] text-slate-500">
              19:00-05:00 の推移（実測 &amp; 予測 / 男性・女性）
            </p>
          </div>

          {loading && (
            <p className="text-[10px] text-slate-500">データ取得中…</p>
          )}
          {error && (
            <p className="text-[10px] text-rose-400">
              データ取得に失敗しました（ベース表示中）
            </p>
          )}
          {!loading && !error && !hasData && (
            <p className="text-[10px] text-amber-300">
              データがまだありません。計測待ちか、閉店時間帯の可能性があります。
            </p>
          )}
        </div>

        {canControlRange && (
          <div className="flex flex-col gap-2 rounded-2xl border border-slate-800 bg-slate-950/60 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-wrap items-center gap-1">
                {RANGE_MODE_OPTIONS.map((opt) => {
                  const active = activeRangeMode === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        onChangeRangeMode(opt.id);
                        if (opt.id === "custom") {
                          setTimeout(() => openDatePicker(), 0);
                        }
                      }}
                      className={[
                        "rounded-full border px-3 py-1 text-[11px] font-semibold transition",
                        active
                          ? "border-amber-300/80 bg-amber-400/10 text-amber-100"
                          : "border-slate-700 bg-slate-950 text-slate-200 hover:border-slate-500",
                      ].join(" ")}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-2 md:ml-auto">
                <input
ref={dateInputRef}
                  type="date"
                  value={customDate}
                  onChange={(e) => {
                    const next = e.target.value;
                    onChangeCustomDate?.(next);
                    onChangeRangeMode("custom");
                  }}
                  className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                />
                {selectedBaseDate && (
                  <span className="text-[11px] text-slate-500">
                    表示: {selectedBaseDate}（19:00-05:00）
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="grid gap-2 text-xs md:grid-cols-5">
          <MetricBox label="♂ 男性人数" value={`${snapshot.nowMen} 人`} tone="male" />
          <MetricBox label="♀ 女性人数" value={`${snapshot.nowWomen} 人`} tone="female" />
          <MetricBox
            label="男女比（男:女）"
            value={`${snapshot.nowMen}:${snapshot.nowWomen}`}
          />
          <MetricBox label="混雑度" value={snapshot.level} />
          <MetricBox label="おすすめ度" value={snapshot.recommendation || "データなし"} />
        </div>
      </section>

      <section className="rounded-3xl border border-slate-800 bg-black p-3 shadow-[0_18px_60px_rgba(0,0,0,0.85)]">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
            timeline
          </p>
          <p className="text-[11px] text-slate-500">
            実線=実測 / 点線=予測（データなしの時間帯は空欄）
          </p>
        </div>

        <div className="mt-3 h-72 w-full min-w-0 rounded-2xl bg-gradient-to-b from-slate-950 via-black to-black p-3">
          {isClient && (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={snapshot.series}
                margin={{ top: 5, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: "#9ca3af" }}
                  stroke="#4b5563"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "#9ca3af" }}
                  stroke="#4b5563"
                  allowDecimals={false}
                />
                <Tooltip content={<TimelineTooltip />} />
                <Legend
                  wrapperStyle={{ fontSize: 10, color: "#9ca3af" }}
                  iconSize={8}
                />

                <Area
                  type="monotone"
                  dataKey="menActual"
                  stroke="none"
                  fill="#38bdf8"
                  fillOpacity={0.24}
                  connectNulls
                  legendType="none"
                />
                <Area
                  type="monotone"
                  dataKey="womenActual"
                  stroke="none"
                  fill="#f472b6"
                  fillOpacity={0.24}
                  connectNulls
                  legendType="none"
                />

                <Line
                  type="monotone"
                  dataKey="menActual"
                  name="男性：実測"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="womenActual"
                  name="女性：実測"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />

                <Line
                  type="monotone"
                  dataKey="menForecast"
                  name="男性：予測"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="5 4"
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="womenForecast"
                  name="女性：予測"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="5 4"
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      <section className={`${cardClass} p-3 text-xs`}>
        <FeedbackPoll storeSlug={storeSlug} />
      </section>

      <section className={`${cardClass} p-3 text-xs`}>
        <SecondVenuesList storeSlug={storeSlug} />
      </section>

      <footer className="mt-1 border-t border-slate-900 pt-3 text-[10px] text-slate-500">
        <p>
          実装例: この UI コンポーネントを{" "}
          <code className="rounded bg-slate-900 px-1">src/app/page.tsx</code>{" "}
          や <code className="rounded bg-slate-900 px-1">src/app/store/[id]/page.tsx</code>{" "}
          で使い、バックエンドの <code className="rounded bg-slate-900 px-1">/api/range</code>{" "}
          や <code className="rounded bg-slate-900 px-1">/api/forecast_today</code>{" "}
          と接続して表示します。
        </p>
      </footer>
    </div>
  );
}

type MetricBoxProps = {
  label: string;
  value: string;
  sub?: string;
  tone?: "male" | "female" | "default";
};

function MetricBox({ label, value, sub, tone = "default" }: MetricBoxProps) {
  const valueColorClass =
    tone === "male"
      ? "text-sky-400"
      : tone === "female"
      ? "text-pink-400"
      : "text-slate-50";

  return (
    <div className="rounded-xl bg-slate-950/90 p-2 ring-1 ring-slate-800">
      <p className="text-[10px] text-slate-400">{label}</p>
      <p className={`mt-1 text-sm font-semibold ${valueColorClass}`}>{value}</p>
      {sub && <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p>}
    </div>
  );
}

type FeedbackPollProps = {
  storeSlug: string;
};

type FeedbackOptionId = "success" | "no_success" | "useful" | "useless";
type FeedbackCounts = Record<FeedbackOptionId, number>;

const FEEDBACK_OPTIONS: { id: FeedbackOptionId; label: string }[] = [
  { id: "success", label: "お持ち帰りできた" },
  { id: "no_success", label: "お持ち帰りできなかった" },
  { id: "useful", label: "役に立った" },
  { id: "useless", label: "あまり役立たなかった" },
];

function isFeedbackOptionId(value: string): value is FeedbackOptionId {
  return (
    value === "success" ||
    value === "no_success" ||
    value === "useful" ||
    value === "useless"
  );
}

function getTodayFeedbackKeyBase(storeSlug: string) {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  return `meguribi_feedback_${storeSlug}_${today}`;
}

function FeedbackPoll({ storeSlug }: FeedbackPollProps) {
  const [selected, setSelected] = useState<FeedbackOptionId | null>(null);
  const [counts, setCounts] = useState<FeedbackCounts>({
    success: 0,
    no_success: 0,
    useful: 0,
    useless: 0,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;

    const base = getTodayFeedbackKeyBase(storeSlug);

    const voted = window.localStorage.getItem(base);
    if (voted && isFeedbackOptionId(voted)) setSelected(voted);
    else setSelected(null);

    const rawCounts = window.localStorage.getItem(`${base}_counts`);
    if (rawCounts) {
      try {
        const parsed = JSON.parse(rawCounts) as Partial<FeedbackCounts>;
        setCounts((prev) => ({ ...prev, ...parsed }));
      } catch {
        // ignore
      }
    } else {
      setCounts({ success: 0, no_success: 0, useful: 0, useless: 0 });
    }
  }, [storeSlug]);

  const handleClick = (id: FeedbackOptionId) => {
    if (selected) return;

    setSelected(id);
    setCounts((prev) => {
      const next: FeedbackCounts = { ...prev, [id]: (prev[id] ?? 0) + 1 };

      if (typeof window !== "undefined") {
        const base = getTodayFeedbackKeyBase(storeSlug);
        window.localStorage.setItem(base, id);
        window.localStorage.setItem(`${base}_counts`, JSON.stringify(next));
      }

      return next;
    });
  };

  const getButtonClasses = (id: FeedbackOptionId, active: boolean) => {
    const base =
      "flex items-center justify-between gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition";
    if (id === "success") {
      return (
        base +
        (active
          ? " border-emerald-400 bg-emerald-500/20 text-emerald-100"
          : " border-emerald-500/60 bg-transparent text-emerald-200 hover:bg-emerald-500/10")
      );
    }
    if (id === "no_success") {
      return (
        base +
        (active
          ? " border-rose-400 bg-rose-500/20 text-rose-100"
          : " border-rose-500/60 bg-transparent text-rose-200 hover:bg-rose-500/10")
      );
    }
    if (id === "useful") {
      return (
        base +
        (active
          ? " border-sky-400 bg-sky-500/20 text-sky-100"
          : " border-sky-500/60 bg-transparent text-sky-200 hover:bg-sky-500/10")
      );
    }
    return (
      base +
      (active
        ? " border-slate-400 bg-slate-500/20 text-slate-100"
        : " border-slate-500/60 bg-transparent text-slate-200 hover:bg-slate-700/30")
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-100">
          フィードバック（任意投票）
        </p>
        <p className="text-[10px] text-slate-500">
          1日1回だけ、ローカルに保存（店舗別）
        </p>
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-4">
        {FEEDBACK_OPTIONS.map((opt) => {
          const active = selected === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleClick(opt.id)}
              disabled={!!selected && !active}
              className={getButtonClasses(opt.id, active)}
            >
              <span>{opt.label}</span>
              <span className="text-[11px] font-semibold text-slate-50">
                {counts[opt.id] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <p className="mt-2 text-[11px] text-emerald-300">
          ありがとうございます。改善のヒントとして活用します。
        </p>
      )}
    </div>
  );
}
