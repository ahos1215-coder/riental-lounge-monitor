// frontend/src/app/hooks/useStorePreviewData.ts
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_STORE, getStoreMetaBySlugOrDefault } from "../config/stores";
import {
  FORECAST_MAX_RETRIES,
  FORECAST_REFRESH_MS,
  FORECAST_RETRY_DELAYS_MS,
  RANGE_LIMIT_BY_MODE,
  addDays,
  buildBaseSnapshot,
  buildSeries,
  computeFreshness,
  computeInitialRefreshDelayMs,
  computeNightBaseDate,
  computeNightWindowFromBaseDate,
  computeSelectedNightBaseDate,
  formatYMD,
  hasSeriesData,
  isNightCompleted,
  isWithinNight,
  nightDateYYYYMMDD,
  parseForecastPoints,
  parseRangePoints,
  pickLatestActualPoint,
  type ForecastPoint,
  type ForecastStatus,
  type PreviewRangeMode,
  type StoreSnapshot,
} from "./storePreviewSnapshot";
import {
  assembleStoreSnapshot,
  resolveLatestActualTs,
} from "@/lib/forecast/assembleSnapshot";
import { jstHm } from "@/lib/date/jst";

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
  NightWindowRange,
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
 * サーバー（page.tsx）で焼き込んだ initialSnapshot を、今のクライアント状態で
 * 初期シードとして採用してよいかを判定する純粋関数。true のときだけシードを使う。
 *
 * 採用しない条件:
 * 1. slug 不一致、または `completedNight` の判定が焼いた時点と変わっている
 *    （夜境界 19:00 / 翌05:00 JST をまたいだ）。そのまま使うと前夜の回顧、または
 *    逆に古い進行中表示になる。
 * 2. ライブ表示（clientCompletedNight===false）のときだけ、seed の `latestActualTs` が
 *    既に "stale"（既定 20 分＝REALTIME_STALE_THRESHOLD_MIN）。ISR の
 *    stale-while-revalidate で古い HTML が返ると、営業中なのに「閉店中・最終22:05時点」の
 *    ような誤表示を最大90秒（遅延バックグラウンド再取得まで）出し続けるため。
 *    完了済みの夜は回顧表示で古い実測が正しい値なので、この鮮度チェックはしない。
 *    latestActualTs が null（実測ゼロ）は computeFreshness が "none" を返すので破棄しない。
 *
 * 採用しない場合は baseSnapshot から即 run() して 60-90s のシード遅延をスキップする。
 * 再現条件の詳細は useStorePreviewData.seedGuard.test.ts の各 it を参照。
 */
/**
 * 鮮度表示の巻き戻り（「1分前」→70秒後に「13分前」）を防ぐモノトニシティ・ガード。
 * true なら「取得結果の方が古い」＝上書き拒否。
 *
 * today（ライブ）の遅延再取得やポーリングは CDN → Next → backend のキャッシュ層を通るため、
 * 既に表示中より古い実測が返ることがある（X-Vercel-Cache STALE で最大 13 分の事例あり）。
 *
 * - どちらかが null/不正 → false（上書き許可）。特に current が null のモード切替直後
 *   （loading リセットで null に戻る）はガード対象外にして従来どおり反映させる。
 * - 両方が有効な ISO 文字列で candidate < current のときだけ true。
 *
 * 再現条件の詳細は useStorePreviewData.monotonicityGuard.test.ts の各 it を参照。
 */
export function isStaleRefetch(
  candidateLatestActualTs: string | null | undefined,
  currentLatestActualTs: string | null | undefined,
): boolean {
  if (!candidateLatestActualTs || !currentLatestActualTs) return false;
  const candidate = new Date(candidateLatestActualTs).getTime();
  const current = new Date(currentLatestActualTs).getTime();
  if (Number.isNaN(candidate) || Number.isNaN(current)) return false;
  return candidate < current;
}

export function isUsableInitialSnapshot(
  initialSnapshot:
    | Pick<StoreSnapshot, "slug" | "completedNight" | "latestActualTs">
    | null
    | undefined,
  slug: string,
  clientCompletedNight: boolean,
  now: Date = new Date(),
): boolean {
  if (
    !initialSnapshot ||
    initialSnapshot.slug !== slug ||
    initialSnapshot.completedNight !== clientCompletedNight
  ) {
    return false;
  }
  // ライブ表示（今日進行中）のときだけ seed の実測鮮度をチェックする。完了済みの夜は
  // 古い実測が仕様どおり（回顧的表示）なので対象外。latestActualTs が null（実測なし）の
  // 場合は computeFreshness が "none" を返すため、この判定だけでは破棄されない。
  if (!clientCompletedNight) {
    const freshness = computeFreshness(initialSnapshot.latestActualTs, now);
    if (freshness.state === "stale") return false;
  }
  return true;
}

/**
 * PREVIEW 用のデータ取得フック
 * - /api/range（store + limit + 日付の from/to）を叩き、選択した baseDate の夜窓（19:00-05:00）を
 *   フロントで絞り込む（夜窓＝時刻粒度の判定はサーバーに入れない。plan/DECISIONS #3/#4）
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
    () => getStoreMetaBySlugOrDefault(storeSlug ?? DEFAULT_STORE),
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

  // クライアントがマウントした時点の「今」。completedNight 判定と、直後の seed 鮮度チェック
  // （BUG #9）の両方で同じ基準時刻を使う。レンダーごとに new Date() を呼んで判定し直すと、
  // 壁時計が進んだだけで usableInitialSnapshot の真偽・参照が変わり、それが下の useEffect の
  // 依存配列を通じて意図しない再実行（初期シード消費後の不要な即時再フェッチ）を招くため、
  // マウント時に一度だけ確定させる。
  const mountNow = useMemo(() => new Date(), []);

  // クライアントがマウントした時点での「今日の夜は既に完了しているか」。initialSnapshot は
  // today モード前提で焼かれているので、page.tsx と同じ computeNightBaseDate(now) で判定する。
  // マウント時に一度だけ評価すれば十分（夜境界は 12 時間に 1 度しか動かない）。
  const clientCompletedNight = useMemo(
    () => isNightCompleted(computeNightBaseDate(mountNow), mountNow),
    [mountNow],
  );

  // 初期表示（today モード・同じ店舗）にのみ適用可能な initialSnapshot かどうか。
  // rangeMode の初期値は常に "today" なので、マウント直後はこの判定がそのまま有効。
  // slug 一致・夜境界一致（completedNight）に加え、ライブ表示では seed の実測鮮度も
  // チェックする（BUG #9: 滅多に訪問されないページで ISR が古い HTML を返し、営業中なのに
  // 「閉店中・最終◯時◯分時点」と誤表示するのを防ぐ。詳細は isUsableInitialSnapshot 参照）。
  // 破棄されると usableInitialSnapshot=null → shouldPreserveInitialSeed=false
  // → initialRunDelayMs=0 で即 run() が走り、古い/誤った表示を最大60-90s出し続ける問題を防ぐ。
  const usableInitialSnapshot = isUsableInitialSnapshot(
    initialSnapshot,
    meta.slug,
    clientCompletedNight,
    mountNow,
  )
    ? initialSnapshot ?? null
    : null;

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
        // 表示対象の夜が既に終わっている（窓の終わり=翌05:00 JSTを過ぎた）かどうか。
        // - 「今日」モードでも、05:00-19:00 の間（次の夜がまだ始まっていない）は
        //   ここで true になり、直近に終わった夜の答え合わせ表示に切り替わる。
        // - 「昨日」「先週」は実質的に常に true。カスタムで未来日を選んだ場合のみ false。
        const completedNight = isNightCompleted(baseDate, now);

        // RANGE_LIMIT_BY_MODE は Record<PreviewRangeMode, number> で全モード網羅（?? 不要）
        const rangeLimit = RANGE_LIMIT_BY_MODE[rangeMode];
        const fromYmd = formatYMD(baseDate);
        const toYmd = formatYMD(addDays(baseDate, 1));
        const rangeUrl =
          `/api/range?store=${encodeURIComponent(meta.slug)}` +
          `&from=${encodeURIComponent(fromYmd)}` +
          `&to=${encodeURIComponent(toYmd)}` +
          `&limit=${rangeLimit}`;

        // 予測の取得先を決める:
        // - 完了済みの夜（モード問わず）: その夜に実際配信されていた予測のスナップショット
        //   （/api/forecast_snapshot）。実測(実線)の上に予測(点線)を夜全体で重ねて
        //   答え合わせできるようにする（buildSeries の overlayAllForecast=true）。
        // - 進行中の「今日」: 従来通り /api/forecast_today（未来区間のみ点線＝isFutureOnly）。
        // - それ以外（非 today モードで対象の夜がまだ完了していない＝未来日カスタム等）:
        //   予測は取得しない（従来通り）。
        const forecastUrl = completedNight
          ? `/api/forecast_snapshot?store=${encodeURIComponent(meta.slug)}` +
            `&date=${encodeURIComponent(nightDateYYYYMMDD(baseDate))}`
          : rangeMode === "today"
            ? `/api/forecast_today?store=${encodeURIComponent(meta.slug)}`
            : null;
        // 高速化: range と forecast を同時発火、range が先に解決したら即描画
        const rangePromise = fetch(rangeUrl, { signal }).then((r) => r.json().catch(() => ({})));
        const forecastPromise = forecastUrl
          ? fetch(forecastUrl, { signal }).then((r) => r.json().catch(() => ({})))
          : Promise.resolve(null);
        // タブ連打（AbortController.abort()）で range が先に reject すると、この関数は
        // 下の `await rangePromise` で throw して catch へ抜け、同じ signal の forecastPromise を
        // await しないまま放置する。その拒否が未処理のまま残ると
        // pageerror('signal is aborted without reason') になる。解決値は変えずに
        // 保険のハンドラだけ付けて未処理拒否を防ぐ（正常系は下の `await forecastPromise` が従来どおり）。
        forecastPromise.catch(() => {});

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

        // 再試行中は forecastStatus を引き継ぎ、それ以外は loading 段階の "idle" を維持
        const initialForecastStatus: ForecastStatus =
          rangeMode !== "today"
            ? "idle"
            : forecastRetryAttempt > 0
              ? "retrying"
              : "idle";

        // 夜窓フィルタで空になっても、最新の実測値があればカードは0固定にしない
        // （now 値の優先順・ピーク・丸めは assembleStoreSnapshot に集約。判断値はここで決めて渡す）。
        const baseSnapshotResolved: StoreSnapshot = assembleStoreSnapshot({
          base: baseSnapshot,
          series: effectiveActualSeries,
          latestActual,
          actualOnlyPeak: false,
          level: hasData ? "データ取得済み" : "データなし",
          recommendation: hasData ? "データ取得済み" : "データなし",
          forecastUpdatedLabel: "--:--",
          hasData,
          forecastStatus: initialForecastStatus,
          // latestActual（夜窓フィルタ前の全データ）の ts を優先し、無ければ夜窓内系列の最新実測点で代替する。
          latestActualTs: resolveLatestActualTs(latestActual, effectiveActualSeries),
          completedNight,
        });

        if (!cancelled) {
          setState((prev) => {
            // BUG B (rank4) モノトニシティ・ガード: today のバックグラウンド再取得が
            // 現在表示中より古い実測を返した場合は上書きしない（次の再取得を待つ）。
            // モード切替（今日→昨日等）は effect 再実行時に loading へリセットされ
            // prev.snapshot.latestActualTs が null に戻ってから走るため対象外。
            if (
              rangeMode === "today" &&
              isStaleRefetch(baseSnapshotResolved.latestActualTs, prev.snapshot.latestActualTs)
            ) {
              return prev.loading ? { ...prev, loading: false } : prev;
            }
            return { loading: false, error: null, snapshot: baseSnapshotResolved };
          });
        }

        // range と予測(forecastPoints)をマージして描画する共通処理。completedNight の
        // スナップショット合流・today 進行中の forecast_today 合流の両方から使う。
        const applyMergedForecast = (
          forecastPoints: ForecastPoint[],
          overlayAllForecast: boolean,
        ) => {
          const mergedSeries = buildSeries(rangePoints, forecastPoints, overlayAllForecast);
          const effectiveMergedSeries =
            mergedSeries.length > 0 ? mergedSeries : baseSnapshotResolved.series;
          // 完了済みの夜（overlayAllForecast=true）は実測(実線)の上に予測(点線)を夜全体で
          // 重ねるため、系列に予測点が併存する。ピークは「その夜に実際どれだけ混んだか」を
          // 表すべきなので実測点のみから算出する（予測点で上書きされるのを防ぐ）。進行中の
          // today（overlayAllForecast=false）は従来どおり予測ピークも含めた算出を維持する。
          const mergedSnapshot: StoreSnapshot = assembleStoreSnapshot({
            base: baseSnapshotResolved,
            series: effectiveMergedSeries,
            latestActual,
            actualOnlyPeak: completedNight,
            // 合流では level/recommendation/latestActualTs/completedNight は実測スナップショットの値を
            // そのまま引き継ぐ（旧実装のスプレッド継承と同じ。再計算しない）。
            level: baseSnapshotResolved.level,
            recommendation: baseSnapshotResolved.recommendation,
            // hook 側の「予測が合流できた」表示は無条件に現在時刻。page.tsx とは意図的に別物。
            forecastUpdatedLabel: jstHm(new Date()),
            hasData: hasSeriesData(mergedSeries) || baseSnapshotResolved.hasData,
            forecastStatus: "ok",
            latestActualTs: baseSnapshotResolved.latestActualTs,
            completedNight: baseSnapshotResolved.completedNight,
          });
          if (!cancelled) {
            setState((prev) => {
              // BUG B (rank4) モノトニシティ・ガード（forecast 合流後も同様に適用）。
              if (
                rangeMode === "today" &&
                isStaleRefetch(mergedSnapshot.latestActualTs, prev.snapshot.latestActualTs)
              ) {
                return prev.loading ? { ...prev, loading: false } : prev;
              }
              return { loading: false, error: null, snapshot: mergedSnapshot };
            });
          }
        };

        // 非 today モード（昨日/先週/カスタム）は、予測の有無に関わらず実測 range が
        // 生命線。コールド店舗＋営業ピークの輻輳で range が一過性に空応答になると、以前は
        // グラフが空のまま自己回復せず「昨日のグラフが出ない」と誤認されていた。実測が
        // 1 件も取れなかった場合だけ、今日モードの予測再試行と同じバックオフで range を
        // 再取得する（データが元々存在しない過去日では空が正なので、上限到達後は静かに終了）。
        // これは forecastUrl の有無（completedNight かどうか）とは独立に行う。
        if (rangeMode !== "today" && !hasData && forecastRetryAttempt < FORECAST_MAX_RETRIES) {
          if (cancelled) return;
          // 直前で forecastRetryAttempt < FORECAST_MAX_RETRIES(=配列長) を確認済み（?? 不要）
          const delay = FORECAST_RETRY_DELAYS_MS[forecastRetryAttempt];
          retryTimer = setTimeout(() => {
            if (!cancelled) {
              run(forecastRetryAttempt + 1);
            }
          }, delay);
        }

        // 予測を取得しないケース（非 today モードで対象の夜がまだ完了していない＝
        // 未来日カスタム等）は、実測のみのスナップショットで終了。
        if (!forecastUrl) {
          return;
        }

        // forecast が完了したら合流（range と並行で既にリクエスト済み）
        const forecastJson = await forecastPromise;
        if (!forecastJson) {
          return;
        }

        if (completedNight) {
          // 完了済みの夜: その夜に配信されていた予測のスナップショットをそのまま
          // 夜全体に重ねる（答え合わせ）。無い/空（まだ記録されていない新しい夜・
          // この機能導入前の古い夜）場合はエラー扱いにせず、再試行もせず実測のみで
          // 静かに終了する（forecastStatus は idle のまま = UI に警告を出さない）。
          const snapshotOk = Boolean((forecastJson as { ok?: boolean })?.ok);
          const allSnapshotPoints = snapshotOk ? parseForecastPoints(forecastJson) : [];
          const snapshotPoints = allSnapshotPoints.filter((p) =>
            isWithinNight(p.ts, nightWindow),
          );
          if (snapshotPoints.length === 0) {
            return;
          }
          applyMergedForecast(snapshotPoints, true);
          return;
        }

        // ここから先は「進行中の今日」のみ（completedNight===false && rangeMode==="today"）。
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
            // 直前で forecastRetryAttempt < FORECAST_MAX_RETRIES(=配列長) を確認済み（?? 不要）
            const delay = FORECAST_RETRY_DELAYS_MS[forecastRetryAttempt];
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
        applyMergedForecast(forecastPoints, false);
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

    // サーバーの initialSnapshot をこの初回実行で seed 消費する場合、最初のバックグラウンド
    // 再取得だけ 60-90s 遅らせる（page.tsx 側は revalidate=120 で焼いた実データなので、
    // マウント直後に同じ内容をほぼ確実に再取得するだけの二重フェッチを避ける）。
    // initialSnapshot が無いコールド CSR パスは従来通り即時実行（挙動を変えない）。
    const initialRunDelayMs = computeInitialRefreshDelayMs(shouldPreserveInitialSeed);
    let initialRunTimer: ReturnType<typeof setTimeout> | null = null;
    if (initialRunDelayMs > 0) {
      initialRunTimer = setTimeout(() => {
        if (!cancelled) run();
      }, initialRunDelayMs);
    } else {
      run();
    }

    let timer: ReturnType<typeof setInterval> | null = null;
    // 今日モードは実測/予測が動くので15分ごとに再取得して予測線を更新する。
    // (遅延させた初回実行とは独立に、マウント時点から15分の定期ループを開始する)
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
      if (initialRunTimer) clearTimeout(initialRunTimer);
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
