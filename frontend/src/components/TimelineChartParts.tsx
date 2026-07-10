"use client";

import type { LegendProps, TooltipProps } from "recharts";

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

  const labels: Record<string, string> = {
    "男性：実測": "男性（実測）",
    "女性：実測": "女性（実測）",
    "男性：予測": "男性（予測）",
    "女性：予測": "女性（予測）",
  };

  const filtered = payload.filter((entry) => {
    const name = entry.name ?? "";
    return !!labels[name];
  });
  if (!filtered.length) return null;

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
          valueText = `${Math.round(raw)}${unit}`;
        }

        const color = entry.color ?? "#e5e7eb";

        return (
          <p key={`${name}-${idx}`} style={{ color }}>
            {labels[name] ?? name}: {valueText}
          </p>
        );
      })}
    </div>
  );
}
