import type { PublicFacts } from "@/lib/blog/publicFacts";

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

  const showFactsDebug = process.env.NEXT_PUBLIC_SHOW_FACTS_DEBUG === "1";
  const notes = facts.quality_flags?.notes ?? [];
  const hasNotes = Array.isArray(notes) && notes.length > 0;

  return (
    <section className="mt-8 overflow-hidden rounded-2xl border border-white/10 bg-black/30">
      <div className="border-b border-white/10 px-5 py-3">
        <h2 className="text-sm font-bold text-white">10秒まとめ（Facts）</h2>
        <p className="mt-1 text-xs text-white/55">
          記事本文ではなく、公開して良い最小Factsから自動表示しています。
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 px-5 py-5 sm:grid-cols-3">
        <div className="rounded-xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs text-white/50">到着目安</p>
          <p className="mt-1 text-lg font-black">{peak ?? "—"}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs text-white/50">避けたい時間</p>
          <p className="mt-1 text-lg font-black">{avoid ?? "—"}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs text-white/50">混雑ラベル</p>
          <p className="mt-1 text-lg font-black">{label ?? "—"}</p>
        </div>
      </div>

      {showFactsDebug && hasNotes && (
        <div className="border-t border-white/10 px-5 py-4">
          <p className="text-xs font-bold text-white/80">注意</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-white/65">
            {notes.slice(0, 4).map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
