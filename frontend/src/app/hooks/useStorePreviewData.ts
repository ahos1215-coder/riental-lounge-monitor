// frontend/src/app/hooks/useStorePreviewData.ts
import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_STORE,
  getStoreMetaBySlug,
  type StoreMeta,
} from "../config/stores";

export type TimeSeriesPoint = {
  label: string;
  menActual: number | null;
  womenActual: number | null;
  menForecast: number | null;
  womenForecast: number | null;
};

export type StoreSnapshot = {
  slug: string;
  name: string;
  area: string;
  level: string;
  nowTotal: number;
  nowMen: number;
  nowWomen: number;
  peakTimeLabel: string;
  peakTotal: number;
  recommendation: string;
  series: TimeSeriesPoint[];
  hasData: boolean;
};

type RangePoint = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

type ForecastPoint = {
  ts?: string;
  men_pred?: number;
  women_pred?: number;
  total_pred?: number;
};

type NightWindow = {
  start: Date;
  end: Date;
};

export type StorePreviewState = {
  loading: boolean;
  error: string | null;
  snapshot: StoreSnapshot;
};

function buildEmptySeries(): TimeSeriesPoint[] {
  const labels: string[] = [];
  for (let h = 19; h <= 24; h += 1) {
    labels.push(`${h.toString().padStart(2, "0")}:00`);
  }
  for (let h = 25; h <= 30; h += 1) {
    labels.push(`${(h - 24).toString().padStart(2, "0")}:00`);
  }
  return labels.map((label) => ({
    label,
    menActual: null,
    womenActual: null,
    menForecast: null,
    womenForecast: null,
  }));
}

function buildBaseSnapshot(meta: StoreMeta): StoreSnapshot {
  return {
    slug: meta.slug,
    name: `オリエンタルラウンジ ${meta.label}`,
    area: meta.areaLabel,
    level: "データなし",
    nowTotal: 0,
    nowMen: 0,
    nowWomen: 0,
    peakTimeLabel: "--:--",
    peakTotal: 0,
    recommendation: "データなし",
    series: buildEmptySeries(),
    hasData: false,
  };
}

function isRangePoint(row: any): row is RangePoint {
  return row && typeof row.ts === "string";
}

function parseRangePoints(raw: unknown): RangePoint[] {
  const anyRaw = raw as any;
  const rows = Array.isArray(anyRaw?.rows)
    ? anyRaw.rows
    : Array.isArray(anyRaw?.data)
    ? anyRaw.data
    : [];
  return rows.filter(isRangePoint);
}

function isForecastPoint(row: any): row is ForecastPoint {
  return row && typeof row.ts === "string";
}

function parseForecastPoints(raw: unknown): ForecastPoint[] {
  const anyRaw = raw as any;
  const rows = Array.isArray(anyRaw?.data) ? anyRaw.data : [];
  return rows.filter(isForecastPoint);
}

function computeNightWindow(now: Date = new Date()): NightWindow {
  const base = new Date(now);
  const isEvening = base.getHours() >= 19;
  const baseDate = new Date(
    base.getFullYear(),
    base.getMonth(),
    base.getDate() + (isEvening ? 0 : -1),
  );

  const start = new Date(baseDate);
  start.setHours(19, 0, 0, 0);

  const end = new Date(baseDate);
  end.setDate(end.getDate() + 1);
  end.setHours(5, 0, 0, 0);

  return { start, end };
}

function isWithinNight(ts: string | undefined, window: NightWindow): boolean {
  if (!ts) return false;
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return false;
  const time = t.getTime();
  return time >= window.start.getTime() && time <= window.end.getTime();
}

function formatLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function buildSeries(
  actuals: RangePoint[],
  forecasts: ForecastPoint[],
): TimeSeriesPoint[] {
  const sortedActuals = [...actuals].sort((a, b) => {
    const ta = new Date(a.ts ?? 0).getTime();
    const tb = new Date(b.ts ?? 0).getTime();
    return ta - tb;
  });

  const sortedForecasts = [...forecasts].sort((a, b) => {
    const ta = new Date(a.ts ?? 0).getTime();
    const tb = new Date(b.ts ?? 0).getTime();
    return ta - tb;
  });

  const lastActualTime =
    sortedActuals.length > 0
      ? new Date(sortedActuals[sortedActuals.length - 1].ts ?? 0).getTime()
      : 0;

  const map = new Map<string, TimeSeriesPoint>();

  for (const p of sortedActuals) {
    if (!p.ts) continue;
    map.set(p.ts, {
      label: formatLabel(p.ts),
      menActual: typeof p.men === "number" ? p.men : null,
      womenActual: typeof p.women === "number" ? p.women : null,
      menForecast: null,
      womenForecast: null,
    });
  }

  for (const p of sortedForecasts) {
    if (!p.ts) continue;
    const t = new Date(p.ts).getTime();
    const isFutureOnly = lastActualTime > 0 && t > lastActualTime;

    const existing = map.get(p.ts);
    const menForecast =
      typeof p.men_pred === "number" ? p.men_pred : existing?.menForecast ?? null;
    const womenForecast =
      typeof p.women_pred === "number"
        ? p.women_pred
        : existing?.womenForecast ?? null;

    if (existing) {
      map.set(p.ts, {
        ...existing,
        menForecast: isFutureOnly ? menForecast : null,
        womenForecast: isFutureOnly ? womenForecast : null,
      });
    } else {
      map.set(p.ts, {
        label: formatLabel(p.ts),
        menActual: null,
        womenActual: null,
        menForecast,
        womenForecast,
      });
    }
  }

  return Array.from(map.entries())
    .sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
    .map(([, v]) => v);
}

function pickCurrentActual(series: TimeSeriesPoint[]) {
  const last = [...series]
    .reverse()
    .find(
      (p) =>
        p.menActual !== null ||
        p.womenActual !== null ||
        p.menForecast !== null ||
        p.womenForecast !== null,
    );
  if (!last) return { nowMen: 0, nowWomen: 0 };
  return {
    nowMen: last.menActual ?? last.menForecast ?? 0,
    nowWomen: last.womenActual ?? last.womenForecast ?? 0,
  };
}

function pickPeak(series: TimeSeriesPoint[]) {
  let bestLabel = "";
  let bestTotal = 0;
  series.forEach((p) => {
    const total =
      (p.menActual ?? 0) +
      (p.womenActual ?? 0) +
      (p.menForecast ?? 0) +
      (p.womenForecast ?? 0);
    if (total > bestTotal) {
      bestTotal = total;
      bestLabel = p.label;
    }
  });
  return { peakTotal: bestTotal, peakTimeLabel: bestLabel || "--:--" };
}

function hasSeriesData(series: TimeSeriesPoint[]) {
  return series.some(
    (p) =>
      p.menActual !== null ||
      p.womenActual !== null ||
      p.menForecast !== null ||
      p.womenForecast !== null,
  );
}

/**
 * PREVIEW 用のデータ取得フック
 * - /api/range と /api/forecast_today を叩き、19:00–05:00 をフロントで絞り込む
 * - データが無い場合でも baseSnapshot を返し、UI を安全に表示する
 */
export function useStorePreviewData(
  storeSlug: string | null | undefined,
): StorePreviewState {
  const meta = useMemo(
    () => getStoreMetaBySlug(storeSlug ?? DEFAULT_STORE),
    [storeSlug],
  );
  const baseSnapshot = useMemo(() => buildBaseSnapshot(meta), [meta]);

  const [state, setState] = useState<StorePreviewState>({
    loading: true,
    error: null,
    snapshot: baseSnapshot,
  });

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setState({ loading: true, error: null, snapshot: baseSnapshot });
      try {
        const nightWindow = computeNightWindow();

        const [rangeRes, forecastRes] = await Promise.all([
          fetch(`/api/range?store=${encodeURIComponent(meta.slug)}&limit=400`),
          fetch(`/api/forecast_today?store=${encodeURIComponent(meta.slug)}`),
        ]);

        const rangeJson = await rangeRes.json().catch(() => ({}));
        const forecastJson = await forecastRes.json().catch(() => ({}));

        const allRangePoints = parseRangePoints(rangeJson);
        const allForecastPoints = parseForecastPoints(forecastJson);

        const rangePoints = allRangePoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );
        const forecastPoints = allForecastPoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );

        const series = buildSeries(rangePoints, forecastPoints);
        const effectiveSeries =
          series.length > 0 ? series : baseSnapshot.series;
        const hasData = hasSeriesData(series);

        const { nowMen, nowWomen } = pickCurrentActual(effectiveSeries);
        const { peakTotal, peakTimeLabel } = pickPeak(effectiveSeries);

        const snapshot: StoreSnapshot = {
          ...baseSnapshot,
          level: hasData ? "データ取得済み" : "データなし",
          recommendation: hasData ? "データ取得済み" : "データなし",
          nowMen,
          nowWomen,
          nowTotal: nowMen + nowWomen,
          peakTotal,
          peakTimeLabel,
          series: effectiveSeries,
          hasData,
        };

        if (!cancelled) {
          setState({ loading: false, error: null, snapshot });
        }
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        if (!cancelled) {
          setState({
            loading: false,
            error: detail,
            snapshot: { ...baseSnapshot, hasData: false, level: "データなし" },
          });
        }
        // eslint-disable-next-line no-console
        console.error("useStorePreviewData.error", detail);
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [meta, baseSnapshot]);

  return state;
}
