import type { PublicFacts } from "@/lib/blog/publicFacts";

type SeriesPoint = NonNullable<PublicFacts["series_min"]>[number];

function pickValue(point: SeriesPoint): number | null {
  const total = Number(point.total);
  if (Number.isFinite(total)) return total;

  const men = Number(point.men);
  const women = Number(point.women);
  if (Number.isFinite(men) && Number.isFinite(women)) return men + women;
  if (Number.isFinite(men)) return men;
  if (Number.isFinite(women)) return women;
  return null;
}

function toValues(series: SeriesPoint[]): number[] {
  return series.map(pickValue).filter((v): v is number => Number.isFinite(v));
}

export function FactsSparkline({
  series,
  className,
}: {
  series?: PublicFacts["series_min"];
  className?: string;
}) {
  const points = Array.isArray(series) ? series : [];
  const values = toValues(points);

  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);

  const width = 180;
  const height = 48;
  const padding = 4;
  const innerW = width - padding * 2;
  const innerH = height - padding * 2;
  const step = values.length > 1 ? innerW / (values.length - 1) : innerW;

  const coords = values.map((value, idx) => {
    const x = padding + step * idx;
    const y = padding + innerH - ((value - min) / range) * innerH;
    return `${x.toFixed(2)} ${y.toFixed(2)}`;
  });
  const d = coords.map((c, idx) => `${idx === 0 ? "M" : "L"} ${c}`).join(" ");

  const classes = className ?? "h-12 w-full text-amber-300/80";

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={classes} role="img" aria-label="facts trend">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}