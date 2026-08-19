"use client";

export type DailySummaryEntry = {
  date: string;
  day_label_ja: string;
  avg_occupancy: number;
  peak_occupancy: number;
  avg_female_ratio: number;
  sample_count: number;
};

type Props = {
  summary: DailySummaryEntry[];
};

/**
 * 「一番賑わった夜」を選ぶ。ピーク混雑度が最大の夜を選び、**同値のときは平均混雑度で
 * タイブレーク**する。
 *
 * 相席屋（%表示ブランド）はピークが 100% で頭打ちになるため、同値タイが常態化し、
 * 単純な先勝ちだと「週の最初の夜」が毎週固定で選ばれてしまっていた。平均で比べれば
 * 「一晩を通して賑わっていた夜」が選ばれる。平均も同値なら従来どおり先勝ち（安定選択）。
 */
export function pickBusiestNight(summary: DailySummaryEntry[]): DailySummaryEntry | null {
  if (summary.length === 0) return null;
  return summary.reduce((acc, d) => {
    if (d.peak_occupancy > acc.peak_occupancy) return d;
    if (d.peak_occupancy === acc.peak_occupancy && d.avg_occupancy > acc.avg_occupancy) return d;
    return acc;
  }, summary[0]);
}

/**
 * 先週 7 夜分の日別サマリ。
 * 各「夜」は 19:00 〜 翌 04:59 を 1 つの単位として集計済み。
 *
 * Phase 追補 (2026-05): ヒートマップだけでは「いつが特に印象に残った夜か」が
 * 読みにくいので、日別の平均/ピーク混雑度を一覧化する。
 */
export default function WeeklySummary({ summary }: Props) {
  if (summary.length === 0) return null;

  // バー描画用の最大値 (0 で割らないようガード)
  const maxPeak = Math.max(0.001, ...summary.map((d) => d.peak_occupancy || 0));

  // 一番混んだ日を特定して強調（ピーク同値は平均でタイブレーク）
  const busiest = pickBusiestNight(summary);
  if (!busiest) return null;

  return (
    <section className="rounded-2xl border border-white/10 bg-black/40 p-4 md:p-6">
      <h2 className="text-lg font-bold text-white">先週の日別サマリ</h2>
      <p className="mt-1 text-xs text-white/50">
        各夜 (19:00-翌04:59) の平均・ピーク混雑度。一番賑わった夜は{" "}
        <span className="font-semibold text-amber-200">
          {busiest.date.slice(5)} ({busiest.day_label_ja})
        </span>
        。
      </p>

      <div className="mt-4 space-y-2">
        {summary.map((d) => {
          const isBusiest = d.date === busiest.date;
          const peakWidth = (d.peak_occupancy / maxPeak) * 100;
          const avgWidth = (d.avg_occupancy / maxPeak) * 100;
          return (
            <div key={d.date} className="grid grid-cols-[88px_1fr_auto] items-center gap-3">
              <div className="flex items-baseline gap-2 text-xs">
                <span className={`font-semibold ${isBusiest ? "text-amber-200" : "text-white/70"}`}>
                  {d.date.slice(5)}
                </span>
                <span className="text-white/40">({d.day_label_ja})</span>
              </div>
              <div className="relative h-5 overflow-hidden rounded bg-white/5">
                {/* ピーク (淡い) */}
                <div
                  className="absolute inset-y-0 left-0 rounded bg-rose-500/30"
                  style={{ width: `${peakWidth}%` }}
                />
                {/* 平均 (濃い) */}
                <div
                  className="absolute inset-y-0 left-0 rounded bg-rose-500/80"
                  style={{ width: `${avgWidth}%` }}
                />
              </div>
              <div className="text-right text-[11px] text-white/55">
                ピーク {(d.peak_occupancy * 100).toFixed(0)}%
                <span className="ml-2 text-white/35">
                  平均 {(d.avg_occupancy * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center gap-3 text-[10px] text-white/40">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded bg-rose-500/80" />
          平均
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded bg-rose-500/30" />
          ピーク
        </span>
      </div>
    </section>
  );
}
