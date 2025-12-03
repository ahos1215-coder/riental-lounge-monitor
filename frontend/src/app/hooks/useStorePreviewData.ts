// frontend/src/app/hooks/useStorePreviewData.ts
import { useEffect, useMemo, useState } from "react";
import {
  MOCK_STORE_DATA,
  type StoreId,
  type StoreSnapshot,
  type TimeSeriesPoint,
  getSlugFromStoreId,
} from "../../components/MeguribiDashboardPreview";

/** /api/range の1点分（実測） */
type RangePoint = {
  ts?: string;
  men?: number;
  women?: number;
  total?: number;
};

/** /api/forecast_today の1点分（予測） */
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

function isWithinNight(
  ts: string | undefined,
  window: NightWindow,
): boolean {
  if (!ts) return false;
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return false;
  const time = t.getTime();
  return (
    time >= window.start.getTime() &&
    time <= window.end.getTime()
  );
}

function formatLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

/**
 * 実測と予測を 1 本の TimeSeries にマージする。
 * - 実測: そのまま menActual / womenActual
 * - 予測: 「最後の実測時刻より後」のポイントだけ menForecast / womenForecast として描画
 */
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

  // 1) 実測を入れる
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

  // 2) 予測をマージ
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
      // 実測と同じ時刻には「未来分であれば」予測を載せる
      map.set(p.ts, {
        ...existing,
        menForecast: isFutureOnly ? menForecast : null,
        womenForecast: isFutureOnly ? womenForecast : null,
      });
    } else {
      // 実測がない純粋な未来ポイント
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

/** 最新の実測値から「今の人数」を拾う */
function pickCurrentActual(series: TimeSeriesPoint[]) {
  const last = [...series]
    .reverse()
    .find((p) => p.menActual !== null || p.womenActual !== null);
  if (!last) return { nowMen: 0, nowWomen: 0 };
  return {
    nowMen: last.menActual ?? 0,
    nowWomen: last.womenActual ?? 0,
  };
}

/** 実測+予測をざっくり見て、一番多い時刻と人数を取る */
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

/**
 * PREVIEW 用のデータ取得フック
 * - まず MOCK_STORE_DATA をベースにして
 * - /api/range, /api/forecast_today を取得
 * - 成功したらグラフ用 series / 現在人数 / ピーク値を差し替える
 * - 失敗したらダミーデータのまま（エラー文言だけ出す）
 */
export function useStorePreviewData(storeId: StoreId): StorePreviewState {
  const base = useMemo(() => MOCK_STORE_DATA[storeId], [storeId]);
  const [state, setState] = useState<StorePreviewState>({
    loading: true,
    error: null,
    snapshot: base,
  });

  useEffect(() => {
    let cancelled = false;
    const slug = getSlugFromStoreId(storeId);

    async function run() {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      try {
        // いまの時刻から「どの夜(19:00–05:00)を表示するか」を決める
        const nightWindow = computeNightWindow();

        // /api/range は API_CONTRACT.md に従い from/to なしで 1 回だけ
        const [rangeRes, forecastRes] = await Promise.all([
          fetch(
            `/api/range?store=${encodeURIComponent(slug)}&limit=400`,
          ),
          fetch(`/api/forecast_today?store=${encodeURIComponent(slug)}`),
        ]);

        const rangeJson = await rangeRes.json().catch(() => ({}));
        const forecastJson = await forecastRes.json().catch(() => ({}));

        const allRangePoints = parseRangePoints(rangeJson);
        const allForecastPoints = parseForecastPoints(forecastJson);

        // 19:00–05:00 の夜間ウィンドウ内だけに絞り込む
        const rangePoints = allRangePoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );
        const forecastPoints = allForecastPoints.filter((p) =>
          isWithinNight(p.ts, nightWindow),
        );

        const series = buildSeries(rangePoints, forecastPoints);
        const effectiveSeries = series.length > 0 ? series : base.series;

        const { nowMen, nowWomen } = pickCurrentActual(effectiveSeries);
        const { peakTotal, peakTimeLabel } = pickPeak(effectiveSeries);

        const snapshot: StoreSnapshot = {
          ...base,
          nowMen,
          nowWomen,
          nowTotal: nowMen + nowWomen,
          peakTotal,
          peakTimeLabel,
          series: effectiveSeries,
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
            snapshot: base,
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
  }, [storeId, base]);

  return state;
}
