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

/** 18時台便（事前の見通し） vs 21時半便（実測に基づく修正・実況） */
export type BlogEdition = "evening_preview" | "late_update";

export type DraftContext = {
  edition: BlogEdition;
  /** avoid_time は「待ち時間が短い」目安であり、相席の質の最高値とは限らない */
  avoid_time_semantics: "entry_ease_not_social_peak";
  /** ML 2.0 の店舗別推論が使えたかを人間向けに表示 */
  ml_inference_mode: "store_specific_or_forecast" | "range_only";
  /** forecast API reasoning.notes の要約（存在時） */
  ml_signal_notes: string[];
  gender_note: string;
  secondary_wave: { detected: boolean; note: string };
  data_health: { level: "ok" | "sparse" | "concerning"; notes: string[] };
  /** AI 向け短い一行（時間帯別の傾き） */
  hourly_hint: string;
};

export type InsightBuildResult = {
  insight: Insight;
  range: NightWindow;
  quality_flags: { notes: string[] };
  /** Which API produced points before insight */
  source: "api/range" | "api/forecast_today";
  /** forecast date shift rescue */
  shift: "none" | "+1day";
  /** 下書き生成向け: 男女比・ウェーブ検知・データ健全性・エディション */
  draft_context: DraftContext;
};

export type PointWithGender = {
  dt: Date;
  total: number;
  men: number | null;
  women: number | null;
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

/** 同一カレンダー日（JST）0:00〜23:59:59.999。今夜の窓にまだサンプルが無い日中などに使う */
export function dayWindowIso(ymd: string): NightWindow {
  return {
    from: `${ymd}T00:00:00+09:00`,
    to: `${ymd}T23:59:59.999+09:00`,
    label: "Day (JST)",
  };
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

export function collectPointsWithGender(
  rows: unknown[],
  fromIso: string,
  toIso: string,
  options: CollectOptions
): PointWithGender[] {
  const from = new Date(fromIso);
  const to = new Date(toIso);
  const shiftMs = (options.shiftDays ?? 0) * MS_PER_DAY;
  const points: PointWithGender[] = [];

  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const row = r as Record<string, unknown>;
    const dt = parseTimestamp(row);
    if (!dt) continue;
    const shifted = shiftMs ? new Date(dt.getTime() + shiftMs) : dt;
    if (shifted < from || shifted > to) continue;

    const total = computeTotal(row, options.totalKeys, options.menKeys, options.womenKeys);
    if (!Number.isFinite(total)) continue;

    const men = pickNumber(row, options.menKeys);
    const women = pickNumber(row, options.womenKeys);

    points.push({
      dt: shifted,
      total: total as number,
      men: men != null && Number.isFinite(men) ? men : null,
      women: women != null && Number.isFinite(women) ? women : null,
    });
  }

  points.sort((a, b) => a.dt.getTime() - b.dt.getTime());
  return points;
}

function hourJST(d: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo",
    hour: "numeric",
    hour12: false,
  }).formatToParts(d);
  const h = parts.find((p) => p.type === "hour")?.value;
  return h != null ? parseInt(h, 10) : 12;
}

/** JST の現在時刻からエディション推定（LINE 手動テスト時も利用） */
export function inferBlogEditionFromJstNow(date = new Date()): BlogEdition {
  const h = hourJST(date);
  if (h >= 21 || h <= 2) return "late_update";
  return "evening_preview";
}

function sumHourlyTotals(points: PointWithGender[]): Map<number, number> {
  const m = new Map<number, number>();
  for (const p of points) {
    const h = hourJST(p.dt);
    m.set(h, (m.get(h) ?? 0) + p.total);
  }
  return m;
}

function computeDraftContext(
  detailed: PointWithGender[],
  insight: Insight,
  edition: BlogEdition,
  extraQualityNotes: string[],
  options?: { mlInferenceMode?: DraftContext["ml_inference_mode"]; mlSignalNotes?: string[] }
): DraftContext {
  const notes: string[] = [...extraQualityNotes];
  let gender_note =
    "男女別のカウントが十分に取れないため、性別構成については断定しません（データに men/women が無い、または不足）。";

  const withBoth = detailed.filter((p) => p.men != null && p.women != null && p.men! >= 0 && p.women! >= 0);
  if (withBoth.length >= 3) {
    const avgMen = withBoth.reduce((s, p) => s + (p.men as number), 0) / withBoth.length;
    const avgWo = withBoth.reduce((s, p) => s + (p.women as number), 0) / withBoth.length;
    if (avgWo > avgMen * 1.2) {
      gender_note = `サンプル平均では女性のカウントが男性よりやや多めに見える傾向です（参考・推測過多は避けること）。`;
    } else if (avgMen > avgWo * 1.2) {
      gender_note = `サンプル平均では男性のカウントが女性よりやや多めに見える傾向です。相席の成立は人数バランスにも左右されるため、過度に楽観・悲観しない説明にしてください。`;
    } else {
      gender_note = `サンプル平均では男女のカウントのバランスはおおむね近い範囲に見えます（参考）。`;
    }
  }

  const hourly = sumHourlyTotals(detailed);
  const e19 = (hourly.get(19) ?? 0) + (hourly.get(20) ?? 0);
  const e21 = (hourly.get(21) ?? 0) + (hourly.get(22) ?? 0);
  let secondaryWave = { detected: false, note: "21〜22時台の急増パターンは検出できませんでした（サンプル数・時間粒度の制約あり）。" };
  if (detailed.length >= 8 && e19 > 0 && e21 / e19 >= 1.25) {
    secondaryWave = {
      detected: true,
      note:
        "19〜20時台合計と比べて21〜22時台の合計が大きい傾向です。一次会後の合流・二次会層の流入が考えられる時間帯として、**控えめに**言及してよい（断定禁止）。",
    };
  } else if (detailed.length >= 8 && e21 > 0 && e19 === 0) {
    secondaryWave = {
      detected: true,
      note: "21〜22時台にサンプルが集中しているため、深夜帯の盛り上がりが読み取れます（控えめに）。",
    };
  }

  let level: "ok" | "sparse" | "concerning" = "ok";
  if (detailed.length < 6) {
    level = "sparse";
    notes.push("sample_count_low");
  }
  const maxTotal = detailed.length ? Math.max(...detailed.map((p) => p.total)) : 0;
  if (detailed.length > 0 && maxTotal < 25 && insight.crowd_label === "空き") {
    level = "concerning";
    notes.push("overall_low_activity");
  }
  if (withBoth.length >= 3) {
    const avgMen = withBoth.reduce((s, p) => s + (p.men as number), 0) / withBoth.length;
    const avgWo = withBoth.reduce((s, p) => s + (p.women as number), 0) / withBoth.length;
    if (avgMen > avgWo * 1.6) {
      if (level === "ok") level = "concerning";
      notes.push("male_heavy_imbalance");
    }
  }

  const hourlyParts: string[] = [];
  for (const h of [18, 19, 20, 21, 22, 23]) {
    const v = hourly.get(h);
    if (v != null && v > 0) hourlyParts.push(`${h}時台計:${Math.round(v)}`);
  }
  const hourly_hint =
    hourlyParts.length > 0
      ? `時間帯別の合計（参考・粒度は元データ依存）: ${hourlyParts.join(", ")}`
      : "時間帯別の十分な分解はできません。";

  return {
    edition,
    avoid_time_semantics: "entry_ease_not_social_peak",
    ml_inference_mode: options?.mlInferenceMode ?? "range_only",
    ml_signal_notes: options?.mlSignalNotes ?? [],
    gender_note,
    secondary_wave: secondaryWave,
    data_health: { level, notes },
    hourly_hint,
  };
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

function isAbortError(e: unknown): boolean {
  const anyE = e as any;
  return anyE?.name === "AbortError";
}

/**
 * Flask `/api/range` は店舗・limit により応答が数十秒になることがある。
 * 既定 10s だと Abort され `api_range_error:This operation was aborted` になるため、
 * Cron / LINE パイプラインでは 40s（Vercel 側 `maxDuration` 60s・Gemini 処理と整合）を既定とする。
 */
const DEFAULT_BACKEND_FETCH_TIMEOUT_MS = 40_000;

function backendFetchTimeoutMs(): number {
  const raw = process.env.BLOG_BACKEND_FETCH_TIMEOUT_MS?.trim();
  if (!raw) return DEFAULT_BACKEND_FETCH_TIMEOUT_MS;
  const n = Number.parseInt(raw, 10);
  if (Number.isFinite(n) && n >= 5_000 && n <= 120_000) return n;
  return DEFAULT_BACKEND_FETCH_TIMEOUT_MS;
}

async function fetchJson(url: string, timeoutMs?: number): Promise<unknown> {
  const ms = timeoutMs ?? backendFetchTimeoutMs();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);

  try {
    const res = await fetch(url, {
      headers: { accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`fetch failed: ${res.status} ${res.statusText} (${url})`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
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
  console.log("[insight] fetchRangeRows start", { store, limit });
  const data = await fetchJson(url);
  const rows = pickArray(data);
  console.log("[insight] fetchRangeRows done", { rows: rows.length });
  return rows;
}

export async function fetchForecastRows(
  backendBase: string,
  store: string
): Promise<{ rows: unknown[]; reasoningNotes: string[] }> {
  const base = backendBase.replace(/\/+$/, "");
  const url = `${base}/api/forecast_today?store=${encodeURIComponent(store)}`;
  console.log("[insight] fetchForecastRows start", { store });
  const data = await fetchJson(url);
  const rows = pickArray(data);
  const reasoning =
    data && typeof data === "object" && "reasoning" in (data as Record<string, unknown>)
      ? (data as Record<string, unknown>).reasoning
      : null;
  const notes =
    reasoning && typeof reasoning === "object" && Array.isArray((reasoning as Record<string, unknown>).notes)
      ? ((reasoning as Record<string, unknown>).notes as unknown[]).filter(
          (v): v is string => typeof v === "string" && v.trim().length > 0
        )
      : [];
  console.log("[insight] fetchForecastRows done", { rows: rows.length, reasoningNotes: notes.length });
  return { rows, reasoningNotes: notes };
}

function errorMessage(err: unknown): string {
  if (typeof err === "string") return err;
  if (err && typeof err === "object" && "message" in err) return String((err as Error).message);
  return String(err);
}

/**
 * Build insight + quality notes for a store slug and calendar date (JST ymd).
 * @param options.edition — 省略時は JST 現在時刻から 18時便 / 21時半便 を推定
 */
export async function buildInsightFromBackend(
  backendBase: string,
  storeSlug: string,
  dateYmd: string,
  limit = 1000,
  options?: { edition?: BlogEdition }
): Promise<InsightBuildResult> {
  let range: NightWindow = nightWindowIso(dateYmd);
  const notes: string[] = [];
  let source: InsightBuildResult["source"] = "api/range";
  let shift: InsightBuildResult["shift"] = "none";
  let points: Array<{ dt: Date; total: number }> = [];
  let skipForecastDueToTimeout = false;
  let rangeRows: unknown[] = [];
  let forecastRows: unknown[] = [];
  let forecastReasoningNotes: string[] = [];

  try {
    console.log("[insight] buildInsightFromBackend -> api/range");
    rangeRows = await fetchRangeRows(backendBase, storeSlug, limit);
    points = collectPoints(rangeRows, range.from, range.to, {
      totalKeys: ["total"],
      menKeys: ["men", "male", "m"],
      womenKeys: ["women", "female", "f"],
    });
    console.log("[insight] api/range -> points", { points: points.length, window: "night" });

    // 今夜の窓（19:00〜翌05:00）にまだ1件も無いが、日中のサンプルはある → 同一日の全日（JST）で再集計
    if (points.length === 0 && rangeRows.length > 0) {
      const dayRange = dayWindowIso(dateYmd);
      const dayPts = collectPoints(rangeRows, dayRange.from, dayRange.to, {
        totalKeys: ["total"],
        menKeys: ["men", "male", "m"],
        womenKeys: ["women", "female", "f"],
      });
      console.log("[insight] api/range -> points", { points: dayPts.length, window: "day_fallback" });
      if (dayPts.length > 0) {
        points = dayPts;
        range = dayRange;
        notes.push("night_window_empty_used_full_jst_day");
      }
    }
  } catch (e) {
    const abort = isAbortError(e);
    const msg = errorMessage(e);
    console.error("[insight] api/range failed", { abort, msg });
    notes.push(`api_range_error:${msg}`);
    if (abort) {
      skipForecastDueToTimeout = true;
      notes.push("api_range_timeout_skip_forecast");
    }
  }

  if (points.length === 0) {
    source = "api/forecast_today";
    if (!skipForecastDueToTimeout) {
      try {
        console.log("[insight] buildInsightFromBackend -> api/forecast_today");
        const fetched = await fetchForecastRows(backendBase, storeSlug);
        forecastRows = fetched.rows;
        forecastReasoningNotes = fetched.reasoningNotes;
      } catch (e) {
        notes.push(`forecast_error:${errorMessage(e)}`);
      }
    } else {
      notes.push("skip_forecast_due_to_timeout");
    }

    if (forecastRows.length > 0) {
      points = collectPoints(forecastRows, range.from, range.to, {
        totalKeys: ["total_pred", "total"],
        menKeys: ["men_pred", "men", "male", "m"],
        womenKeys: ["women_pred", "women", "female", "f"],
      });

      if (points.length === 0) {
        const shifted = collectPoints(forecastRows, range.from, range.to, {
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

  const rowsForGender = source === "api/range" ? rangeRows : forecastRows;
  const genderOpts: CollectOptions =
    source === "api/range"
      ? { totalKeys: ["total"], menKeys: ["men", "male", "m"], womenKeys: ["women", "female", "f"] }
      : {
          totalKeys: ["total_pred", "total"],
          menKeys: ["men_pred", "men", "male", "m"],
          womenKeys: ["women_pred", "women", "female", "f"],
          shiftDays: shift === "+1day" ? 1 : undefined,
        };
  const detailed = collectPointsWithGender(rowsForGender, range.from, range.to, genderOpts);

  const edition = options?.edition ?? inferBlogEditionFromJstNow();
  const draft_context = computeDraftContext(detailed, insight, edition, notes, {
    mlInferenceMode: source === "api/forecast_today" ? "store_specific_or_forecast" : "range_only",
    mlSignalNotes: forecastReasoningNotes,
  });

  return {
    insight,
    range,
    quality_flags: {
      notes: [`generated_from:${source}`, `shift:${shift}`, ...notes],
    },
    source,
    shift,
    draft_context,
  };
}
