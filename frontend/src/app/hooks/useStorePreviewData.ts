// frontend/src/app/hooks/useStorePreviewData.ts
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_STORE, getStoreMetaBySlug } from "../config/stores";
import {
  FORECAST_MAX_RETRIES,
  FORECAST_REFRESH_MS,
  FORECAST_RETRY_DELAYS_MS,
  RANGE_LIMIT_BY_MODE,
  addDays,
  buildBaseSnapshot,
  buildSeries,
  computeNightBaseDate,
  computeNightWindowFromBaseDate,
  computeSelectedNightBaseDate,
  formatNowHmJst,
  formatYMD,
  hasSeriesData,
  isWithinNight,
  parseForecastPoints,
  parseRangePoints,
  pickCurrentActual,
  pickLatestActualPoint,
  pickPeak,
  type ForecastStatus,
  type PreviewRangeMode,
  type StoreSnapshot,
} from "./storePreviewSnapshot";

// このフックの利用側（page.tsx を含む）は従来どおり "./useStorePreviewData" から
// 型を import できるよう、純粋関数モジュールの型を re-export しておく
// （実体は storePreviewSnapshot.ts。ロジック重複を避けつつ import パスの互換性を保つ）。
export type {
  PreviewRangeMode,
  TimeSeriesPoint,
  ForecastStatus,
  StoreSnapshot,
  RangePoint,
  ForecastPoint,
  NightWindow,
} from "./storePreviewSnapshot";

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

/**
 * PREVIEW 用のデータ取得フック
 * - /api/range（store/limit のみ）を叩き、選択した baseDate の夜窓（19:00-05:00）をフロントで絞り込む
 * - 予測（/api/forecast_today）は today モードのみ取得（それ以外は取得しない）
 * - データが無い場合でも baseSnapshot を返し、UI を安全に表示する
 * - `initialSnapshot`（サーバーで取得済みのスナップショット）が渡され、かつ現在の表示条件
 *   （today モード・同じ店舗）と一致する場合は、それを初期状態として即座に描画する。
 *   その後も通常どおりフェッチ/ポーリングは走り、最新データに更新される。
 */
export function useStorePreviewData(
  storeSlug: string | null | undefined,
  initialSnapshot?: StoreSnapshot | null,
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

  // 初期表示（today モード・同じ店舗）にのみ適用可能な initialSnapshot かどうか。
  // rangeMode の初期値は常に "today" なので、マウント直後はこの判定がそのまま有効。
  // 計算コストが軽い（null チェックと文字列比較のみ）ので、毎レンダー再計算して問題ない。
  const usableInitialSnapshot =
    initialSnapshot && initialSnapshot.slug === meta.slug ? initialSnapshot : null;

  // initialSnapshot がある場合はサーバー取得済みの実データなので loading:false で即描画する
  // （StoreRealtimeStatusCard 等の loading ゲートでスケルトンに戻さないため）。
  // バックグラウンドの再フェッチ自体は下の useEffect が変わらず開始する。
  const [state, setState] = useState<StorePreviewState>(() =>
    usableInitialSnapshot
      ? { loading: false, error: null, snapshot: usableInitialSnapshot }
      : { loading: true, error: null, snapshot: baseSnapshot },
  );

  // 初回マウントで initialSnapshot を消費したかどうか。React StrictMode の二重実行や
  // 店舗/モード変更による effect の再実行では、通常どおり baseSnapshot にリセットする
  // （seed はあくまで「サーバーから来た最初の一回」だけに適用する）。
  // ref への読み書きはこの useEffect コールバック内でのみ行う（render 中には触れない）。
  const initialSeedConsumedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const signal = controller.signal;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    // このエフェクト実行が「初期シードを保持したままの初回実行」かどうかを判定する。
    // initialSeedConsumedRef が既に true なら（2回目以降の実行 = 店舗/モード変更や
    // ポーリングによる再実行）、usableInitialSnapshot があっても通常どおり
    // baseSnapshot にリセットする。
    const shouldPreserveInitialSeed =
      !!usableInitialSnapshot && !initialSeedConsumedRef.current;
    initialSeedConsumedRef.current = true;

    async function run(forecastRetryAttempt = 0) {
      // 初回 or パラメータ変更時は loading から始める。再試行時はチャートを消さない。
      // ただし、サーバー由来の initialSnapshot をまだ表示中の最初の実行では、
      // 既に実データを表示できているため loading スケルトンへ戻さず、裏側で静かに
      // 最新化する（グラフや数値が一瞬消える/スケルトンに戻るのを防ぐ）。
      if (forecastRetryAttempt === 0) {
        setState((prev) => ({
          loading: shouldPreserveInitialSeed ? false : true,
          error: null,
          snapshot: shouldPreserveInitialSeed ? prev.snapshot : baseSnapshot,
        }));
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
        // latestActual（夜窓フィルタ前の全データ）の ts を優先し、無ければ夜窓内系列の最新実測点で代替する。
        const latestActualTs =
          latestActual?.ts ??
          [...effectiveActualSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
          null;

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
          latestActualTs,
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
  }, [meta, baseSnapshot, rangeMode, customDate, usableInitialSnapshot]);

  return {
    ...state,
    rangeMode,
    setRangeMode,
    customDate,
    setCustomDate,
    selectedBaseDate,
  };
}
