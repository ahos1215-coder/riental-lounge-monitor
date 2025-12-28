import type { PublicFacts } from "@/lib/blog/publicFacts";
import { FactsSparkline } from "@/components/blog/FactsSparkline";

function safeText(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const s = v.trim();
  return s.length ? s : null;
}

export function FactsSummaryCard({ facts }: { facts: PublicFacts | null }) {
  if (!facts) return null;

  const peak = safeText(facts.insight?.peak_time);
  const avoid = safeText(facts.insight?.avoid_time);
  const label = safeText(facts.insight?.crowd_label);

  const series = Array.isArray(facts.series_min) ? facts.series_min : [];
  const showSparkline = series.length >= 2;
  const seriesStart = showSparkline ? series[0]?.t : null;
  const seriesEnd = showSparkline ? series[series.length - 1]?.t : null;
  const showSeriesLabels = Boolean(seriesStart || seriesEnd);

  const showFactsDebug = process.env.NEXT_PUBLIC_SHOW_FACTS_DEBUG === "1";
  const notes = facts.quality_flags?.notes ?? [];
  const hasNotes = Array.isArray(notes) && notes.length > 0;

  return (
    <section className="overflow-hidden rounded-2xl border border-white/10 bg-white/5">
      <div className="px-5 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs text-white/55">Facts</p>
            <p className="mt-1 text-lg font-black text-white">{facts.facts_id}</p>
          </div>
          {facts.store?.label && <div className="text-xs text-white/60">{facts.store.label}</div>}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs text-white/50">ピーク</p>
            <p className="mt-1 text-lg font-black text-white">{peak ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs text-white/50">避けたい時間</p>
            <p className="mt-1 text-lg font-black text-white">{avoid ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs text-white/50">混雑ラベル</p>
            <p className="mt-1 text-lg font-black text-white">{label ?? "—"}</p>
          </div>
        </div>
      </div>

      {showSparkline && (
        <div className="px-5 pb-5">
          <div className="rounded-xl border border-white/10 bg-black/40 p-3">
            <FactsSparkline series={series} />
            {showSeriesLabels && (
              <div className="mt-2 flex items-center justify-between text-[11px] text-white/45">
                <span>{seriesStart ?? ""}</span>
                <span>{seriesEnd ?? ""}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {showFactsDebug && hasNotes && (
        <div className="border-t border-white/10 px-5 py-4">
          <p className="text-xs font-bold text-white/80">注意</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-white/65">
            {notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}