"use client";

import { useState } from "react";

export type HeatmapCell = {
  day: number; // 0=月, 6=日
  hour: number; // 19-23, 0-4
  avg_occupancy: number; // 0.0 - 1.0
  avg_female_ratio: number;
  sample_count: number;
};

export type DayHourHeatmap = {
  cells: HeatmapCell[];
  hour_range: number[];
  day_labels_ja: string[];
  max_avg_occupancy: number;
};

type Props = {
  heatmap: DayHourHeatmap;
};

/**
 * 曜日 × 時間帯の混雑度ヒートマップ。
 *
 * Phase B (Weekly Report 改良): 折れ線グラフでは見えなかった「曜日横断のリズム」
 * (例: 金曜 22 時頃が常に高い) を一目で示す。
 */
export default function WeeklyHeatmap({ heatmap }: Props) {
  const [hoverCell, setHoverCell] = useState<HeatmapCell | null>(null);

  const hours = heatmap.hour_range;
  const days = heatmap.day_labels_ja;
  const cellMap = new Map<string, HeatmapCell>();
  for (const c of heatmap.cells) {
    cellMap.set(`${c.day}-${c.hour}`, c);
  }

  // 混雑度に応じた色 (rose 系の透明度を変える)。サンプルなしのセルは灰色。
  const cellStyle = (cell: HeatmapCell | undefined): React.CSSProperties => {
    if (!cell || cell.sample_count === 0) {
      return { backgroundColor: "rgba(100, 116, 139, 0.08)", border: "1px solid rgba(255,255,255,0.04)" };
    }
    const intensity = Math.min(1, Math.max(0.05, cell.avg_occupancy));
    return {
      backgroundColor: `hsla(345, 80%, ${15 + intensity * 40}%, ${0.3 + intensity * 0.7})`,
      border: "1px solid rgba(255,255,255,0.06)",
    };
  };

  return (
    <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
      <h2 className="text-lg font-bold text-white">曜日 × 時間帯のリズム</h2>
      <p className="mt-1 text-xs text-white/50">
        過去 1 週間の混雑度を曜日 × 時間帯で集計しました。色が濃いほど人が多い時間帯です。
      </p>

      <div className="mt-4 overflow-x-auto">
        <div className="inline-block min-w-full">
          {/* ヘッダー行: 時間ラベル */}
          <div
            className="grid gap-1"
            style={{ gridTemplateColumns: `40px repeat(${hours.length}, minmax(28px, 1fr))` }}
          >
            <div />
            {hours.map((h) => (
              <div
                key={`h-${h}`}
                className="text-center text-[10px] font-medium text-white/50"
              >
                {h.toString().padStart(2, "0")}
              </div>
            ))}
          </div>

          {/* 各曜日の行 */}
          {days.map((dayLabel, dayIdx) => (
            <div
              key={`d-${dayIdx}`}
              className="mt-1 grid gap-1"
              style={{ gridTemplateColumns: `40px repeat(${hours.length}, minmax(28px, 1fr))` }}
            >
              <div className="flex items-center justify-end pr-1 text-[11px] font-medium text-white/60">
                {dayLabel}
              </div>
              {hours.map((h) => {
                const cell = cellMap.get(`${dayIdx}-${h}`);
                return (
                  <div
                    key={`c-${dayIdx}-${h}`}
                    className="aspect-square cursor-pointer rounded transition hover:ring-2 hover:ring-white/40"
                    style={cellStyle(cell)}
                    onMouseEnter={() => cell && setHoverCell(cell)}
                    onMouseLeave={() => setHoverCell(null)}
                    title={
                      cell && cell.sample_count > 0
                        ? `${dayLabel}曜 ${h.toString().padStart(2, "0")}時台: 混雑度 ${(cell.avg_occupancy * 100).toFixed(0)}% / 女性比 ${(cell.avg_female_ratio * 100).toFixed(0)}% (${cell.sample_count}サンプル)`
                        : `${dayLabel}曜 ${h.toString().padStart(2, "0")}時台: データなし`
                    }
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* ホバー時の詳細表示 */}
      <div className="mt-3 min-h-[1.5rem] text-[11px] text-white/60">
        {hoverCell && hoverCell.sample_count > 0 ? (
          <span>
            <span className="font-bold text-white/80">{days[hoverCell.day]}曜 {hoverCell.hour.toString().padStart(2, "0")}時台:</span>{" "}
            混雑度 <span className="text-rose-300">{(hoverCell.avg_occupancy * 100).toFixed(0)}%</span> ・
            女性比 <span className="text-pink-300">{(hoverCell.avg_female_ratio * 100).toFixed(0)}%</span>
            <span className="ml-2 text-white/40">({hoverCell.sample_count} サンプル)</span>
          </span>
        ) : (
          <span className="text-white/30">セルにマウスを乗せると詳細が表示されます</span>
        )}
      </div>

      {/* カラーレジェンド */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-white/40">
        <span>混雑度:</span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-3 w-6 rounded"
            style={{ backgroundColor: "hsla(345, 80%, 18%, 0.3)" }}
          />
          低
        </span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-3 w-6 rounded"
            style={{ backgroundColor: "hsla(345, 80%, 35%, 0.65)" }}
          />
          中
        </span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-3 w-6 rounded"
            style={{ backgroundColor: "hsla(345, 80%, 55%, 1.0)" }}
          />
          高
        </span>
      </div>
    </section>
  );
}
