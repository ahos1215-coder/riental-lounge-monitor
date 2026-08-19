"use client";

import type { LegendProps, TooltipProps } from "recharts";
import { jstHm } from "@/lib/date/jst";

type TimelinePayloadEntry = {
  name?: string;
  value?: number | null;
  color?: string;
};

type TimelineTooltipProps = TooltipProps<number, string> & {
  label?: string | number;
  payload?: TimelinePayloadEntry[];
  /** 値の単位（"人" or "%"）。相席屋は席の埋まり具合% を表示。 */
  unit?: string;
};

type TimelineLegendPayloadItem = {
  value?: string | number;
  color?: string;
};
type TimelineLegendProps = LegendProps & {
  payload?: TimelineLegendPayloadItem[];
};

export function TimelineLegend(props: TimelineLegendProps) {
  const payload = props.payload;
  const items = Array.isArray(payload) ? payload : [];
  if (!items.length) return null;
  const labels: Record<string, string> = {
    "女性：予測": "女性 · 予測",
    "女性：実測": "女性 · 実測",
    "男性：予測": "男性 · 予測",
    "男性：実測": "男性 · 実測",
  };
  const order: Record<string, number> = {
    "女性：予測": 0,
    "女性：実測": 1,
    "男性：予測": 2,
    "男性：実測": 3,
  };
  const filtered = items
    .filter((entry) => {
      const raw = (entry?.value ?? "").toString();
      return raw in labels;
    })
    .sort((a, b) => {
      const av = (a?.value ?? "").toString();
      const bv = (b?.value ?? "").toString();
      return (order[av] ?? 99) - (order[bv] ?? 99);
    });
  if (!filtered.length) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10px] text-slate-300">
      {filtered.map((entry, idx) => {
        const raw = (entry?.value ?? "").toString();
        const value = labels[raw] ?? raw;
        const color = entry?.color ?? "#cbd5e1";
        return (
          <span key={`${value}-${idx}`} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-[2px] w-3 rounded"
              style={{ backgroundColor: color }}
            />
            <span>{value}</span>
          </span>
        );
      })}
    </div>
  );
}

export function TimelineTooltip({ active, payload, label = "", unit = "" }: TimelineTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  // 短縮ラベル: スマホでグラフの上に重なる面積を最小にするため「男性（実測）」→「男・実」。
  // 系列の色（実測/予測で同色・線種違い）と併せて判別できる。
  const labels: Record<string, string> = {
    "男性：実測": "男・実",
    "女性：実測": "女・実",
    "男性：予測": "男・予",
    "女性：予測": "女・予",
  };

  const filtered = payload.filter((entry) => {
    const name = entry.name ?? "";
    return !!labels[name] && typeof entry.value === "number";
  });
  if (!filtered.length) return null;

  return (
    <div
      style={{
        backgroundColor: "rgba(2,6,23,0.92)",
        border: "1px solid #1f2937",
        borderRadius: 8,
        fontSize: 11,
        lineHeight: 1.2,
        padding: "4px 8px",
        whiteSpace: "nowrap",
        display: "flex",
        alignItems: "center",
        gap: 8,
        boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
      }}
    >
      <span style={{ color: "#e5e7eb", fontVariantNumeric: "tabular-nums" }}>
        {typeof label === "number" ? jstHm(new Date(label)) : label}
      </span>
      {filtered.map((entry, idx) => {
        const name = entry.name ?? "";
        const raw = entry.value;
        const valueText = typeof raw === "number" ? `${Math.round(raw)}${unit}` : "-";
        const color = entry.color ?? "#e5e7eb";
        return (
          <span key={`${name}-${idx}`} style={{ color, fontVariantNumeric: "tabular-nums" }}>
            {labels[name] ?? name} {valueText}
          </span>
        );
      })}
    </div>
  );
}
