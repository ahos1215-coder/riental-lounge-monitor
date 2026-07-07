// frontend/src/app/hooks/useStorePreviewData.ts
import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_STORE,
  getStoreMetaBySlug,
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
};

type RangePoint = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

type ForecastPoint = {
  ts?: string;
  // 履歴データ不足の店舗ではバックエンドが null を返す（0.0 との区別のため）。
  men_pred?: number | null;
  women_pred?: number | null;
  total_pred?: number | null;
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

export type StorePreviewControls = {
  rangeMode: PreviewRangeMode;
  setRangeMode: (mode: PreviewRangeMode) => void;
  customDate: string; // yyyy-mm-dd
  setCustomDate: (date: string) => void;
  selectedBaseDate: string; // yyyy-mm-dd
};

const FORECAST_REFRESH_MS = 15 * 60 * 1000;

// 予測 API が空応答だった場合の自動再試行設定。
// 一過性の Supabase Storage 接続リセットや ML モデルプリロード待ちを想定し、
// 段階的に間隔を広げて最大 3 回まで再試行する。
const FORECAST_RETRY_DELAYS_MS: readonly number[] = [5_000, 15_000, 45_000];
const FORECAST_MAX_RETRIES = FORECAST_RETRY_DELAYS_MS.length;

const RANGE_LIMIT_BY_MODE: Record<PreviewRangeMode, number> = {
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

function buildBaseSnapshot(meta: StoreMeta): StoreSnapshot {
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

function formatYMD(date: Date): string {
  const y = date.getFullYear();
  const m = (date.getMonth() + 1).toString().padStart(2, "0");
  const d = date.getDate().toString().padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function parseYMD(value: string): Date | null {
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
function computeNightBaseDate(now: Date): Date {
  const p = jstDateParts(now);
  const base = new Date(p.year, p.month - 1, p.day);
  if (p.hour < 19) {
    base.setDate(base.getDate() - 1);
  }
  return base;
}

function computeNightWindowFromBaseDate(baseDate: Date): NightWindow {
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

function computeSelectedNightBaseDate(
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
  return d.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });
}

function formatNowHmJst(date: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function buildSeries(
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
    nowMen: Math.round(last.menActual ?? last.menForecast ?? 0),
    nowWomen: Math.round(last.womenActual ?? last.womenForecast ?? 0),
  };
}

function pickPeak(series: TimeSeriesPoint[]) {
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

function hasSeriesData(series: TimeSeriesPoint[]) {
  return series.some(
    (p) =>
      p.menActual !== null ||
      p.womenActual !== null ||
      p.menForecast !== null ||
      p.womenForecast !== null,
  );
}

function pickLatestActualPoint(points: RangePoint[]) {
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
  };
}

/**
 * PREVIEW 用のデータ取得フック
 * - /api/range（store/limit のみ）を叩き、選択した baseDate の夜窓（19:00-05:00）をフロントで絞り込む
 * - 予測（/api/forecast_today）は today モードのみ取得（それ以外は取得しない）
 * - データが無い場合でも baseSnapshot を返し、UI を安全に表示する
 */
export function useStorePreviewData(
  storeSlug: string | null | undefined,
): StorePreviewState & StorePreviewControls {
  const meta = useMemo(
    () => getStoreMetaBySlug(storeSlug ?? DEFAULT_STORE),
    [storeSlug],
  );
  const baseSnapshot = useMemo(() => buildBaseSnapshot(meta), [meta]);

  const [rangeMode, setRangeMode] = useState<PreviewRangeMode>("today");
  const [customDate, setCustomDate] = useState<string>(() =>
    formatYMD(computeNightBaseDate(new Date())),
  );

  const selectedBaseDate = useMemo(() => {
    const base = computeSelectedNightBaseDate(rangeMode, customDate, new Date());
    return formatYMD(base);
  }, [rangeMode, customDate]);

  const [state, setState] = useState<StorePreviewState>({
    loading: true,
    error: null,
    snapshot: baseSnapshot,
  });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const signal = controller.signal;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    async function run(forecastRetryAttempt = 0) {
      // 初回 or パラメータ変更時は loading から始める。再試行時はチャートを消さない。
      if (forecastRetryAttempt === 0) {
        setState({ loading: true, error: null, snapshot: baseSnapshot });
      }
      try {
        const now = new Date();
        const baseDate = computeSelectedNightBaseDate(rangeMode, customDate, now);
        const nightWindow = computeNightWindowFromBaseDate(baseDate);

        const rangeLimit = RANGE_LIMIT_BY_MODE[rangeMode] ?? 400;
        const fromYmd = formatYMD(baseDate);
        const toYmd = formatYMD(addDays(baseDate, 1));
        const rangeUrl =
          `/api/range?store=${encodeURIComponent(meta.slug)}` +
          `&from=${encodeURIComponent(fromYmd)}` +
          `&to=${encodeURIComponent(toYmd)}` +
          `&limit=${rangeLimit}`;

        const forecastUrl = `/api/forecast_today?store=${encodeURIComponent(meta.slug)}`;
        // 高速化: range と forecast を同時発火、range が先に解決したら即描画
        const rangePromise = fetch(rangeUrl, { signal }).then((r) => r.json().catch(() => ({})));
        const forecastPromise = rangeMode === "today"
          ? fetch(forecastUrl, { signal }).then((r) => r.json().catch(() => ({})))
          : Promise.resolve(null);

        const rangeJson = await rangePromise;

        const allRangePoints = parseRangePoints(rangeJson);
        const rangePoints = allRangePoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );
        const actualOnlySeries = buildSeries(rangePoints, []);
        const effectiveActualSeries =
          actualOnlySeries.length > 0 ? actualOnlySeries : baseSnapshot.series;
        const latestActual = pickLatestActualPoint(allRangePoints);
        const hasData = hasSeriesData(actualOnlySeries) || latestActual !== null;

        // 夜窓フィルタで空になっても、最新の実測値があればカードは0固定にしない。
        const current = pickCurrentActual(effectiveActualSeries);
        const nowMen = latestActual?.nowMen ?? current.nowMen;
        const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
        const { peakTotal, peakTimeLabel, peakMen: peakMenVal, peakWomen: peakWomenVal } = pickPeak(effectiveActualSeries);

        // 再試行中は forecastStatus を引き継ぎ、それ以外は loading 段階の "idle" を維持
        const initialForecastStatus: ForecastStatus =
          rangeMode !== "today"
            ? "idle"
            : forecastRetryAttempt > 0
              ? "retrying"
              : "idle";

        const baseSnapshotResolved: StoreSnapshot = {
          ...baseSnapshot,
          level: hasData ? "データ取得済み" : "データなし",
          recommendation: hasData ? "データ取得済み" : "データなし",
          nowMen: Math.round(nowMen),
          nowWomen: Math.round(nowWomen),
          nowTotal: Math.round(nowMen + nowWomen),
          peakTotal: Math.round(peakTotal),
          peakTimeLabel,
          peakMen: peakMenVal,
          peakWomen: peakWomenVal,
          forecastUpdatedLabel: "--:--",
          series: effectiveActualSeries,
          hasData,
          forecastStatus: initialForecastStatus,
        };

        if (!cancelled) {
          setState({ loading: false, error: null, snapshot: baseSnapshotResolved });
        }

        // forecast が完了したら合流（range と並行で既にリクエスト済み）
        const forecastJson = await forecastPromise;
        if (!forecastJson || rangeMode !== "today") {
          return;
        }

        // バックエンドが履歴データ不足を明示している場合（店舗の実測データがまだ無く、
        // そもそも予測できない）。この場合は men_pred/women_pred/total_pred が全て null の
        // ダミー行が返ってくるだけなので、再試行しても状況は変わらない。再試行ループには
        // 入らず、即座に「データ準備中」状態にする（0人の平坦な予測ラインを描かない）。
        const isInsufficientHistory = Boolean(
          (forecastJson as { insufficient_history?: boolean })?.insufficient_history,
        );
        if (isInsufficientHistory) {
          if (!cancelled) {
            setState((prev) => ({
              ...prev,
              snapshot: { ...prev.snapshot, forecastStatus: "insufficient_history" },
            }));
          }
          return;
        }

        const allForecastPoints = parseForecastPoints(forecastJson);

        // 予測が空 → ML モデルロード失敗 / Supabase Storage の一過性障害の可能性が高い。
        // 段階的バックオフで自動再試行する。
        if (allForecastPoints.length === 0) {
          if (forecastRetryAttempt < FORECAST_MAX_RETRIES) {
            if (cancelled) return;
            setState((prev) => ({
              ...prev,
              snapshot: { ...prev.snapshot, forecastStatus: "retrying" },
            }));
            const delay = FORECAST_RETRY_DELAYS_MS[forecastRetryAttempt] ?? 45_000;
            retryTimer = setTimeout(() => {
              if (!cancelled) {
                run(forecastRetryAttempt + 1);
              }
            }, delay);
            return;
          }
          // 再試行上限到達 → unavailable
          if (!cancelled) {
            setState((prev) => ({
              ...prev,
              snapshot: { ...prev.snapshot, forecastStatus: "unavailable" },
            }));
          }
          return;
        }

        const forecastPoints = allForecastPoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );
        const mergedSeries = buildSeries(rangePoints, forecastPoints);
        const effectiveMergedSeries =
          mergedSeries.length > 0 ? mergedSeries : baseSnapshotResolved.series;
        const mergedCurrent = pickCurrentActual(effectiveMergedSeries);
        const mergedNowMen = latestActual?.nowMen ?? mergedCurrent.nowMen;
        const mergedNowWomen = latestActual?.nowWomen ?? mergedCurrent.nowWomen;
        const mergedPeak = pickPeak(effectiveMergedSeries);
        const mergedSnapshot: StoreSnapshot = {
          ...baseSnapshotResolved,
          nowMen: Math.round(mergedNowMen),
          nowWomen: Math.round(mergedNowWomen),
          nowTotal: Math.round(mergedNowMen + mergedNowWomen),
          peakTotal: Math.round(mergedPeak.peakTotal),
          peakTimeLabel: mergedPeak.peakTimeLabel,
          peakMen: mergedPeak.peakMen,
          peakWomen: mergedPeak.peakWomen,
          forecastUpdatedLabel: formatNowHmJst(new Date()),
          series: effectiveMergedSeries,
          hasData:
            hasSeriesData(mergedSeries) ||
            baseSnapshotResolved.hasData,
          forecastStatus: "ok",
        };
        if (!cancelled) {
          setState({ loading: false, error: null, snapshot: mergedSnapshot });
        }
      } catch (err) {
        if (signal.aborted) return;
        const detail = err instanceof Error ? err.message : String(err);
        if (!cancelled) {
          setState({
            loading: false,
            error: detail,
            snapshot: {
              ...baseSnapshot,
              hasData: false,
              level: "データなし",
              forecastStatus: rangeMode === "today" ? "unavailable" : "idle",
            },
          });
        }
        console.error("useStorePreviewData.error", detail);
      }
    }

    run();

    let timer: ReturnType<typeof setInterval> | null = null;
    // 今日モードは実測/予測が動くので15分ごとに再取得して予測線を更新する。
    if (rangeMode === "today") {
      timer = setInterval(() => {
        run();
      }, FORECAST_REFRESH_MS);
    }

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearInterval(timer);
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [meta, baseSnapshot, rangeMode, customDate]);

  return {
    ...state,
    rangeMode,
    setRangeMode,
    customDate,
    setCustomDate,
    selectedBaseDate,
  };
}
