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

  // データセット内の最大混雑度で正規化し、ガンマ補正で低中域も見えるようにする。
  // 色相は青 (低) → 紫 → 桃赤 (高) の連続グラデで「違いが分かる」ことを優先。
  const maxOcc = Math.max(0.001, heatmap.max_avg_occupancy || 0);

  const colorForIntensity = (raw: number): string => {
    const normalized = Math.min(1, Math.max(0, raw / maxOcc));
    // ガンマ 0.55: 低い値ほど明るめに伸ばして差を強調
    const t = Math.pow(normalized, 0.55);
    // 220 (青) → 290 (紫) → 345 (桃赤)
    const h = 220 + t * 125;
    const s = 65 + t * 30;
    const l = 22 + t * 38;
    return `hsl(${h}, ${s}%, ${l}%)`;
  };

  const cellStyle = (cell: HeatmapCell | undefined): React.CSSProperties => {
    if (!cell || cell.sample_count === 0) {
      return {
        backgroundColor: "rgba(100, 116, 139, 0.08)",
        border: "1px solid rgba(255,255,255,0.04)",
      };
    }
    return {
      backgroundColor: colorForIntensity(cell.avg_occupancy),
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

      {/* カラーレジェンド (連続グラデで視認性を確保) */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-white/40">
        <span>混雑度:</span>
        <span className="flex items-center gap-1">
          <span className="text-white/55">低</span>
          <span
            className="inline-block h-3 w-32 rounded"
            style={{
              background:
                "linear-gradient(to right, hsl(220, 65%, 22%), hsl(255, 80%, 35%), hsl(290, 85%, 48%), hsl(330, 92%, 55%), hsl(345, 95%, 60%))",
            }}
          />
          <span className="text-white/55">高</span>
        </span>
        {maxOcc > 0 && (
          <span className="ml-2 text-white/30">
            最大値 {(maxOcc * 100).toFixed(0)}% で正規化
          </span>
        )}
      </div>
      <p className="mt-2 text-[10px] text-white/35">
        ※ 0-4 時のデータは前日の夜として集計しています (例: 日曜 00:00 → 土曜の夜)
      </p>
    </section>
  );
}
