// frontend/src/app/hooks/storePreviewSnapshot.ts
//
// useStorePreviewData（クライアントフック）と store/[id]/page.tsx（サーバーコンポーネント）の
// 両方から使う「型・純粋関数」だけを集めたモジュール。React import は一切含まない。
//
// 経緯: これらの純粋関数はもともと useStorePreviewData.ts に同居していたが、"use client" 前提の
// フック（useState/useEffect/useRef を使用）と同じファイルにあると、Server Component
// （store/[id]/page.tsx）がこのファイルを import した際に Next/Turbopack のモジュール境界解析で
// ビルドエラーになる（"You're importing a component that needs `useEffect`..." 等）。
// そのためロジックを重複させず、フレームワーク非依存の純粋関数だけをこの独立ファイルに切り出した。
import {
  buildStoreFullName,
  type StoreMeta,
  type BrandId,
} from "../config/stores";

export type PreviewRangeMode = "today" | "yesterday" | "lastWeek" | "custom";

export type TimeSeriesPoint = {
  ts?: string;
  label: string;
  menActual: number | null;
  womenActual: number | null;
  menForecast: number | null;
  womenForecast: number | null;
};

/**
 * 予測データの取得状態。一過性の Supabase Storage 障害などで `/api/forecast_today`
 * が空配列を返した場合、フックが自動再試行する。UI 側はこの値を見て
 * 「予測を再取得しています」等のヒントを出せる。
 *
 * - `idle`: まだ予測リクエストを行っていない（today モード以外）
 * - `ok`: 予測データを取得できた
 * - `retrying`: 予測が空だったため自動再試行中
 * - `unavailable`: 自動再試行の上限に達してもデータが取れなかった
 * - `insufficient_history`: 店舗の履歴データがまだ無く、そもそも予測できない
 *   （バックエンドが `insufficient_history:true` を返した場合。再試行しても状況は
 *   変わらないため、retrying ループには入らずすぐにこの状態を出す）
 */
export type ForecastStatus = "idle" | "ok" | "retrying" | "unavailable" | "insufficient_history";

export type StoreSnapshot = {
  slug: string;
  name: string;
  area: string;
  /** ブランド（相席屋は人数非公開＝%表示に切替）。 */
  brand: BrandId;
  /** 相席屋の席数（%逆算用）。他ブランドは null。 */
  capacity: number | null;
  level: string;
  nowTotal: number;
  nowMen: number;
  nowWomen: number;
  peakTimeLabel: string;
  peakTotal: number;
  peakMen: number | null;
  peakWomen: number | null;
  recommendation: string;
  forecastUpdatedLabel: string;
  series: TimeSeriesPoint[];
  hasData: boolean;
  forecastStatus: ForecastStatus;
  /**
   * 最新の実測データ点の ts（ISO文字列）。「◯分前更新」の鮮度表示に使う。
   * 実測データが1件も無い場合は null（表示側は「データなし」扱い）。
   */
  latestActualTs: string | null;
};

export type RangePoint = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

export type ForecastPoint = {
  ts?: string;
  // 履歴データ不足の店舗ではバックエンドが null を返す（0.0 との区別のため）。
  men_pred?: number | null;
  women_pred?: number | null;
  total_pred?: number | null;
};

export type NightWindow = {
  start: Date;
  end: Date;
};

// 予測 API が空応答だった場合の自動再試行設定。
// 一過性の Supabase Storage 接続リセットや ML モデルプリロード待ちを想定し、
// 段階的に間隔を広げて最大 3 回まで再試行する。
// server-side snapshot（initialSnapshot）でグラフは既に初回描画できるため、
// クライアント側の再試行は最大待ち時間を 65s → 24s に短縮して体感を早める。
export const FORECAST_RETRY_DELAYS_MS: readonly number[] = [4_000, 8_000, 12_000];
export const FORECAST_MAX_RETRIES = FORECAST_RETRY_DELAYS_MS.length;

export const FORECAST_REFRESH_MS = 15 * 60 * 1000;

// page.tsx（サーバー側の initialSnapshot 取得）も today モードと同じ limit を使う必要があるため export する。
export const RANGE_LIMIT_BY_MODE: Record<PreviewRangeMode, number> = {
  // today は初速重視で軽めにして表示開始を早める
  today: 240,
  yesterday: 1200,
  lastWeek: 1200,
  custom: 1200,
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
    ts: undefined,
    label,
    menActual: null,
    womenActual: null,
    menForecast: null,
    womenForecast: null,
  }));
}

export function buildBaseSnapshot(meta: StoreMeta): StoreSnapshot {
  return {
    slug: meta.slug,
    // ブランド（オリエンタルラウンジ / 相席屋 / JIS）を店舗ごとに正しく表示する。
    // 以前は全店「オリエンタルラウンジ」固定で、相席屋店舗が誤表記されていた。
    name: buildStoreFullName(meta),
    area: meta.areaLabel,
    brand: meta.brand,
    capacity: meta.capacity,
    level: "データなし",
    nowTotal: 0,
    nowMen: 0,
    nowWomen: 0,
    peakTimeLabel: "--:--",
    peakTotal: 0,
    peakMen: null,
    peakWomen: null,
    recommendation: "データなし",
    forecastUpdatedLabel: "--:--",
    series: buildEmptySeries(),
    hasData: false,
    forecastStatus: "idle",
    latestActualTs: null,
  };
}

function isRangePoint(row: unknown): row is RangePoint {
  return !!row && typeof row === "object" && typeof (row as RangePoint).ts === "string";
}

export function parseRangePoints(raw: unknown): RangePoint[] {
  const obj = raw as { rows?: unknown; data?: unknown } | null | undefined;
  const rows = Array.isArray(obj?.rows) ? obj.rows : Array.isArray(obj?.data) ? obj.data : [];
  return (rows as unknown[]).filter(isRangePoint);
}

function isForecastPoint(row: unknown): row is ForecastPoint {
  return !!row && typeof row === "object" && typeof (row as ForecastPoint).ts === "string";
}

export function parseForecastPoints(raw: unknown): ForecastPoint[] {
  const obj = raw as { data?: unknown } | null | undefined;
  const rows = Array.isArray(obj?.data) ? obj.data : [];
  return (rows as unknown[]).filter(isForecastPoint);
}

export function formatYMD(date: Date): string {
  const y = date.getFullYear();
  const m = (date.getMonth() + 1).toString().padStart(2, "0");
  const d = date.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function parseYMD(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!m) return null;

  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);

  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return null;
  }

  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

// The venues are in Japan and the night window is JST 19:00-05:00. Compute the base
// date and window in Asia/Tokyo regardless of the viewer's device timezone, otherwise
// a non-JST visitor filters/labels the wrong slice. JST is fixed +09:00 (no DST).
function jstDateParts(d: Date): { year: number; month: number; day: number; hour: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
  };
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// baseDate carries the JST night-date via its Y/M/D; it is only read through
// getFullYear/getMonth/getDate for date arithmetic, never as an absolute instant.
export function computeNightBaseDate(now: Date): Date {
  const p = jstDateParts(now);
  const base = new Date(p.year, p.month - 1, p.day);
  if (p.hour < 19) {
    base.setDate(base.getDate() - 1);
  }
  return base;
}

export function computeNightWindowFromBaseDate(baseDate: Date): NightWindow {
  const startYmd = `${baseDate.getFullYear()}-${pad2(baseDate.getMonth() + 1)}-${pad2(baseDate.getDate())}`;
  const nextDay = new Date(baseDate);
  nextDay.setDate(nextDay.getDate() + 1);
  const endYmd = `${nextDay.getFullYear()}-${pad2(nextDay.getMonth() + 1)}-${pad2(nextDay.getDate())}`;
  // Absolute JST instants (+09:00) so isWithinNight's getTime() comparison is correct
  // for any viewer timezone.
  const start = new Date(`${startYmd}T19:00:00+09:00`);
  const end = new Date(`${endYmd}T05:00:00+09:00`);
  return { start, end };
}

export function computeSelectedNightBaseDate(
  mode: PreviewRangeMode,
  customDate: string,
  now: Date,
): Date {
  const todayBase = computeNightBaseDate(now);
  const selected = new Date(todayBase);

  if (mode === "yesterday") {
    selected.setDate(selected.getDate() - 1);
    return selected;
  }

  if (mode === "lastWeek") {
    selected.setDate(selected.getDate() - 7);
    return selected;
  }

  if (mode === "custom") {
    return parseYMD(customDate) ?? todayBase;
  }

  return todayBase;
}

export function isWithinNight(ts: string | undefined, window: NightWindow): boolean {
  if (!ts) return false;
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return false;
  const time = t.getTime();
  return time >= window.start.getTime() && time <= window.end.getTime();
}

function formatLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });
}

export function formatNowHmJst(date: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function buildSeries(
  actuals: RangePoint[],
  forecasts: ForecastPoint[],
): TimeSeriesPoint[] {
  const toRoundedOrNull = (v: unknown): number | null =>
    typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

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
      ts: p.ts,
      label: formatLabel(p.ts),
      menActual: toRoundedOrNull(p.men),
      womenActual: toRoundedOrNull(p.women),
      menForecast: null,
      womenForecast: null,
    });
  }

  for (const p of sortedForecasts) {
    if (!p.ts) continue;
    const t = new Date(p.ts).getTime();
    const isFutureOnly = lastActualTime > 0 && t > lastActualTime;

    const existing = map.get(p.ts);
    const menForecast = toRoundedOrNull(p.men_pred) ?? existing?.menForecast ?? null;
    const womenForecast = toRoundedOrNull(p.women_pred) ?? existing?.womenForecast ?? null;

    if (existing) {
      map.set(p.ts, {
        ...existing,
        ts: p.ts,
        menForecast: isFutureOnly ? menForecast : null,
        womenForecast: isFutureOnly ? womenForecast : null,
      });
    } else {
      map.set(p.ts, {
        ts: p.ts,
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

export function pickCurrentActual(series: TimeSeriesPoint[]) {
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
    nowMen: Math.round(last.menActual ?? last.menForecast ?? 0),
    nowWomen: Math.round(last.womenActual ?? last.womenForecast ?? 0),
  };
}

export function pickPeak(series: TimeSeriesPoint[]) {
  let bestLabel = "";
  let bestTotal = 0;
  let bestMen: number | null = null;
  let bestWomen: number | null = null;
  series.forEach((p) => {
    // actual があればそちらを優先、なければ forecast（二重カウント防止）
    const men = p.menActual ?? p.menForecast ?? 0;
    const women = p.womenActual ?? p.womenForecast ?? 0;
    const total = men + women;
    if (total > bestTotal) {
      bestTotal = total;
      bestLabel = p.label;
      bestMen = men > 0 ? Math.round(men) : null;
      bestWomen = women > 0 ? Math.round(women) : null;
    }
  });
  return { peakTotal: bestTotal, peakTimeLabel: bestLabel || "--:--", peakMen: bestMen, peakWomen: bestWomen };
}

export function hasSeriesData(series: TimeSeriesPoint[]) {
  return series.some(
    (p) =>
      p.menActual !== null ||
      p.womenActual !== null ||
      p.menForecast !== null ||
      p.womenForecast !== null,
  );
}

export function pickLatestActualPoint(points: RangePoint[]) {
  const sorted = [...points].sort((a, b) => {
    const ta = new Date(a.ts ?? 0).getTime();
    const tb = new Date(b.ts ?? 0).getTime();
    return tb - ta;
  });
  const latest = sorted.find(
    (p) => typeof p.men === "number" || typeof p.women === "number",
  );
  if (!latest) return null;
  return {
    nowMen: typeof latest.men === "number" ? Math.round(latest.men) : 0,
    nowWomen: typeof latest.women === "number" ? Math.round(latest.women) : 0,
    // 「◯分前更新」用に ts も保持する（以前は破棄していた）。
    ts: typeof latest.ts === "string" ? latest.ts : null,
  };
}
