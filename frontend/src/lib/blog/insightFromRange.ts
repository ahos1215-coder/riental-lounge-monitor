/**
 * Night-window insight from /api/range and /api/forecast_today.
 * Ported from frontend/scripts/generate-public-facts.mjs (same behavior).
 */

const MS_PER_DAY = 24 * 60 * 60 * 1000;

export type NightWindow = { from: string; to: string; label: string };

export type Insight = {
  peak_time: string;
  avoid_time: string;
  crowd_label: string;
};

export type InsightBuildResult = {
  insight: Insight;
  range: NightWindow;
  quality_flags: { notes: string[] };
  /** Which API produced points before insight */
  source: "api/range" | "api/forecast_today";
  /** forecast date shift rescue */
  shift: "none" | "+1day";
};

function fmtYmdTokyo(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function fmtHmTokyo(d: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function ymdPlusDays(ymd: string, days: number): string {
  const base = new Date(`${ymd}T00:00:00+09:00`);
  const d = new Date(base.getTime() + days * MS_PER_DAY);
  return fmtYmdTokyo(d);
}

export function nightWindowIso(ymd: string): NightWindow {
  const from = `${ymd}T19:00:00+09:00`;
  const toYmd = ymdPlusDays(ymd, 1);
  const to = `${toYmd}T05:00:00+09:00`;
  return { from, to, label: "Tonight" };
}

function normalizeIso(s: string): string {
  return s.replace(/\.(\d{3})\d+/, ".$1");
}

function parseTimestamp(row: Record<string, unknown>): Date | null {
  const v =
    row.ts ??
    row.t ??
    row.time ??
    row.datetime ??
    row.at ??
    row.created_at ??
    row.createdAt ??
    null;

  if (v == null) return null;
  if (typeof v === "number" && Number.isFinite(v)) return new Date(v);
  if (typeof v !== "string") return null;

  const s = normalizeIso(v.trim());
  if (!s) return null;

  if (/[zZ]$/.test(s) || /[+-]\d\d:\d\d$/.test(s)) return new Date(s);
  return new Date(`${s}+09:00`);
}

function pickNumber(obj: Record<string, unknown>, keys: string[]): number | null {
  for (const k of keys) {
    const n = Number(obj[k]);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function computeTotal(
  row: Record<string, unknown>,
  totalKeys: string[],
  menKeys: string[],
  womenKeys: string[]
): number | null {
  const total = pickNumber(row, totalKeys);
  if (total != null) return total;
  const men = pickNumber(row, menKeys);
  const women = pickNumber(row, womenKeys);
  if (men != null && women != null) return men + women;
  return null;
}

type CollectOptions = {
  totalKeys: string[];
  menKeys: string[];
  womenKeys: string[];
  shiftDays?: number;
};

export function collectPoints(
  rows: unknown[],
  fromIso: string,
  toIso: string,
  options: CollectOptions
): Array<{ dt: Date; total: number }> {
  const from = new Date(fromIso);
  const to = new Date(toIso);
  const shiftMs = (options.shiftDays ?? 0) * MS_PER_DAY;
  const points: Array<{ dt: Date; total: number }> = [];

  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const row = r as Record<string, unknown>;
    const dt = parseTimestamp(row);
    if (!dt) continue;
    const shifted = shiftMs ? new Date(dt.getTime() + shiftMs) : dt;
    if (shifted < from || shifted > to) continue;

    const total = computeTotal(row, options.totalKeys, options.menKeys, options.womenKeys);
    if (!Number.isFinite(total)) continue;

    points.push({ dt: shifted, total: total as number });
  }

  points.sort((a, b) => a.dt.getTime() - b.dt.getTime());
  return points;
}

export function computeInsight(points: Array<{ dt: Date; total: number }>): Insight {
  if (points.length === 0) {
    return { peak_time: "", avoid_time: "", crowd_label: "" };
  }

  let peak = points[0];
  let avoid = points[0];
  for (const p of points) {
    if (p.total > peak.total) peak = p;
    if (p.total < avoid.total) avoid = p;
  }

  const max = peak.total;
  let crowd_label = "空き";
  if (max >= 120) crowd_label = "混み";
  else if (max >= 80) crowd_label = "ほどよい";

  return {
    peak_time: fmtHmTokyo(peak.dt),
    avoid_time: fmtHmTokyo(avoid.dt),
    crowd_label,
  };
}

async function fetchJson(url: string): Promise<unknown> {
  const res = await fetch(url, { headers: { accept: "application/json" }, cache: "no-store" });
  if (!res.ok) throw new Error(`fetch failed: ${res.status} ${res.statusText} (${url})`);
  return res.json();
}

function pickArray(data: unknown): unknown[] {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    if (Array.isArray(o.rows)) return o.rows;
    if (Array.isArray(o.data)) return o.data;
  }
  return [];
}

export async function fetchRangeRows(backendBase: string, store: string, limit: number): Promise<unknown[]> {
  const base = backendBase.replace(/\/+$/, "");
  const url = `${base}/api/range?store=${encodeURIComponent(store)}&limit=${encodeURIComponent(String(limit))}`;
  const data = await fetchJson(url);
  return pickArray(data);
}

export async function fetchForecastRows(backendBase: string, store: string): Promise<unknown[]> {
  const base = backendBase.replace(/\/+$/, "");
  const url = `${base}/api/forecast_today?store=${encodeURIComponent(store)}`;
  const data = await fetchJson(url);
  return pickArray(data);
}

function errorMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err && typeof err === "object" && "message" in err) return String((err as Error).message);
  return String(err);
}

/**
 * Build insight + quality notes for a store slug and calendar date (JST ymd).
 */
export async function buildInsightFromBackend(
  backendBase: string,
  storeSlug: string,
  dateYmd: string,
  limit = 1000
): Promise<InsightBuildResult> {
  const { from, to, label } = nightWindowIso(dateYmd);
  const notes: string[] = [];
  let source: InsightBuildResult["source"] = "api/range";
  let shift: InsightBuildResult["shift"] = "none";
  let points: Array<{ dt: Date; total: number }> = [];

  try {
    const rows = await fetchRangeRows(backendBase, storeSlug, limit);
    points = collectPoints(rows, from, to, {
      totalKeys: ["total"],
      menKeys: ["men", "male", "m"],
      womenKeys: ["women", "female", "f"],
    });
  } catch (e) {
    notes.push(`api_range_error:${errorMessage(e)}`);
  }

  if (points.length === 0) {
    source = "api/forecast_today";
    let forecastRows: unknown[] = [];
    try {
      forecastRows = await fetchForecastRows(backendBase, storeSlug);
    } catch (e) {
      notes.push(`forecast_error:${errorMessage(e)}`);
    }

    if (forecastRows.length > 0) {
      points = collectPoints(forecastRows, from, to, {
        totalKeys: ["total_pred", "total"],
        menKeys: ["men_pred", "men", "male", "m"],
        womenKeys: ["women_pred", "women", "female", "f"],
      });

      if (points.length === 0) {
        const shifted = collectPoints(forecastRows, from, to, {
          totalKeys: ["total_pred", "total"],
          menKeys: ["men_pred", "men", "male", "m"],
          womenKeys: ["women_pred", "women", "female", "f"],
          shiftDays: 1,
        });
        if (shifted.length > 0) {
          points = shifted;
          shift = "+1day";
        }
      }
    }
  }

  if (points.length === 0) notes.push("no_samples_in_window");

  const insight = computeInsight(points);

  return {
    insight,
    range: { from, to, label },
    quality_flags: {
      notes: [`generated_from:${source}`, `shift:${shift}`, ...notes],
    },
    source,
    shift,
  };
}
