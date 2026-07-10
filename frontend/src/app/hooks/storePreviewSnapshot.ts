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
  isPercentCrowdBrand,
  seatFullnessPercent,
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
  /**
   * ピーク（最も混雑した系列点）の ts（ISO文字列・絶対時刻）。null は不明。
   * 「ピークまで あと約…」チップが、ピークを既に過ぎた後も"これから盛り上がる"方向へ
   * 誤誘導しないよう、描画時に `new Date()` と比較して「ピークは過ぎたか」を判定するために使う。
   */
  peakTs: string | null;
  /**
   * 表示対象の夜が既に終わっている（回顧的表示）かどうか。
   * - 「昨日」「先週」「過去日カスタム」は常に true。
   * - 「今日」モードでも、夜が既に終わった（05:00-19:00 の間など）場合は true。
   * 完了済みの夜では「ピークまで あと約…」や「ピークは過ぎました（進行中の含意）」を
   * 出さない（答え合わせ表示なので現在進行の文言は誤解を招く）。
   */
  completedNight: boolean;
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

// initialSnapshot（サーバー seed）を消費した直後の最初のバックグラウンド再取得を
// どれだけ遅らせるかの範囲（ms）。page.tsx の initialSnapshot は revalidate=120 で
// 最大でも約2分しか経っていない実データなので、マウント直後に同じ内容をほぼ確実に
// 再取得するだけの二重フェッチ（サーバー側 SSR フェッチとクライアント側フェッチの
// back-to-back 発火）を避ける。15分ごとの定期更新ループ自体はこの遅延と無関係に
// マウント時点から起算し続ける。
export const INITIAL_REFRESH_DELAY_MIN_MS = 60_000;
export const INITIAL_REFRESH_DELAY_MAX_MS = 90_000;

/**
 * 初回バックグラウンド再取得までの遅延（ms）を決める純粋関数。
 * - `shouldPreserveInitialSeed` が false（initialSnapshot 無しのコールド CSR、または
 *   店舗/モード変更後の再実行）の場合は 0 を返す＝従来通り即時実行（挙動を変えない）。
 * - true の場合は [INITIAL_REFRESH_DELAY_MIN_MS, INITIAL_REFRESH_DELAY_MAX_MS) の範囲で
 *   ジッターさせた遅延を返す（同時にマウントされた多数のカード/タブが一斉に同じ
 *   タイミングでバックエンドを叩くのを避ける）。
 * `random` は 0 以上 1 未満の乱数を返す関数（テスト用に差し替え可能。既定は Math.random）。
 */
export function computeInitialRefreshDelayMs(
  shouldPreserveInitialSeed: boolean,
  random: () => number = Math.random,
): number {
  if (!shouldPreserveInitialSeed) return 0;
  const span = INITIAL_REFRESH_DELAY_MAX_MS - INITIAL_REFRESH_DELAY_MIN_MS;
  const r = random();
  const clamped = Number.isFinite(r) ? Math.min(Math.max(r, 0), 1) : 0;
  return INITIAL_REFRESH_DELAY_MIN_MS + Math.floor(clamped * span);
}

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
    peakTs: null,
    completedNight: false,
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

/**
 * 夜の baseDate（19:00 側の JST 日付）を、スナップショットのストレージキーと同じ
 * YYYYMMDD 形式にする（scripts/snapshot_forecasts.py の `night_date` と一致させる）。
 * baseDate は getFullYear/getMonth/getDate だけで JST の Y/M/D を運ぶ値なので、
 * ここでもそれ以外（getTime 等）は参照しない。
 */
export function nightDateYYYYMMDD(baseDate: Date): string {
  const y = baseDate.getFullYear();
  const m = pad2(baseDate.getMonth() + 1);
  const d = pad2(baseDate.getDate());
  return `${y}${m}${d}`;
}

/**
 * 対象の夜（baseDate 19:00 始まり）が、`now` 時点で既に終わっている（窓の終わり
 * ＝ 翌日 05:00 JST を過ぎている）かどうか。
 * - 「今日」モードでも、05:00-19:00 の間（次の夜がまだ始まっていない）はここで
 *   true になる＝直近に終わった夜の予測スナップショットを見せる対象になる。
 * - 「昨日」「先週」は baseDate が常に過去なので、実質的に常に true。
 * - 「カスタム」で未来日を選んだ場合は false（まだ配信すらされていない）。
 */
export function isNightCompleted(baseDate: Date, now: Date): boolean {
  const window = computeNightWindowFromBaseDate(baseDate);
  return now.getTime() >= window.end.getTime();
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
  // 完了済みの夜の答え合わせ表示専用: true の場合、実測と重なる過去区間でも予測
  // （点線）を null にせず、夜全体に渡って実測(実線)の上に予測(点線)を重ねて描く。
  // デフォルト false は従来どおり（today モード進行中は「実測より未来」の区間だけ
  // 点線を残し、過去区間の二重描画を防ぐ）。
  overlayAllForecast = false,
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
    const keepForecast =
      overlayAllForecast || (lastActualTime > 0 && t > lastActualTime);

    const existing = map.get(p.ts);
    const menForecast = toRoundedOrNull(p.men_pred) ?? existing?.menForecast ?? null;
    const womenForecast = toRoundedOrNull(p.women_pred) ?? existing?.womenForecast ?? null;

    if (existing) {
      map.set(p.ts, {
        ...existing,
        ts: p.ts,
        menForecast: keepForecast ? menForecast : null,
        womenForecast: keepForecast ? womenForecast : null,
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
  let bestTs: string | null = null;
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
      // ピーク時刻の絶対値（ISO）。表示側の「ピークは過ぎたか」判定に使う。
      bestTs = p.ts ?? null;
      bestMen = men > 0 ? Math.round(men) : null;
      bestWomen = women > 0 ? Math.round(women) : null;
    }
  });
  return {
    peakTotal: bestTotal,
    peakTimeLabel: bestLabel || "--:--",
    peakTs: bestTs,
    peakMen: bestMen,
    peakWomen: bestWomen,
  };
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

/**
 * ピーク（最も混雑した系列点）を既に過ぎたか＝ピーク時刻 < 現在時刻 かどうか。
 * peakTs は絶対時刻（ISO）なので、閲覧者のタイムゾーンに関係なく getTime() 比較で正しい。
 * null/不正な場合は「過ぎたか不明」として false を返す（進行中の夜では従来どおり
 * 「ピークまで あと約…」を出せるよう安全側に倒す）。
 */
export function isPeakPassed(
  peakTs: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!peakTs) return false;
  const t = new Date(peakTs);
  if (Number.isNaN(t.getTime())) return false;
  return t.getTime() < now.getTime();
}

/**
 * 「予測ハイライト」のピーク進捗チップ（1つ、または該当なしで null）を決める純粋関数。
 *
 * バグ修正: 以前は `max(0, peak - now)` だけを見て、ピークを過ぎて客足が引いた後でも
 * 「ピークまで あと約◯人」を出し続け、閉店に向かって数字が増える誤誘導になっていた。
 * さらに完了済みの夜（昨日/過去日）でも同じチップが「あと約◯人」と回顧的に表示していた。
 *
 * 新ルール:
 * - 完了済みの夜（completedNight）: 回顧的表示なので「あと約…」も「ピークは過ぎました」も
 *   出さない（現在進行の含意を避ける）。おすすめ度があればそれにフォールバック。
 * - 進行中でピークを既に過ぎた: 「ピークは過ぎました（落ち着き傾向）」に置き換える。
 * - 進行中でこれからピーク: 従来どおり「ピークまで あと約◯人 / %」。
 */
export function peakProgressChip(
  snapshot: Pick<
    StoreSnapshot,
    "brand" | "capacity" | "peakTotal" | "nowTotal" | "peakTs" | "completedNight" | "recommendation"
  >,
  now: Date = new Date(),
): string | null {
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const cap = snapshot.capacity ?? 0;
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const total = Math.max(0, Math.round(Number(snapshot.nowTotal ?? 0)));
  const rec = snapshot.recommendation?.trim() || "";
  const recChip =
    rec && rec !== "データなし" && rec !== "データ取得済み" ? `おすすめ度 ${rec}` : null;

  // 完了済みの夜は回顧的表示。現在進行の文言は出さず、おすすめ度があればそれを出す。
  if (snapshot.completedNight) {
    return recChip;
  }

  // 進行中でピークを既に過ぎている → 「あと約…」は誤誘導。落ち着き傾向を明示する。
  if (isPeakPassed(snapshot.peakTs, now)) {
    return "ピークは過ぎました（落ち着き傾向）";
  }

  // 進行中でこれからピーク → 従来どおり残り目安を出す。
  if (percentMode) {
    const peakPct = seatFullnessPercent(peak, cap * 2) ?? 0;
    const nowPct = seatFullnessPercent(total, cap * 2) ?? 0;
    const deltaPct = Math.max(0, peakPct - nowPct);
    if (deltaPct > 0) return `ピークまで あと約${deltaPct}%`;
    return recChip;
  }
  const delta = peak > 0 ? Math.max(0, peak - total) : 0;
  if (delta > 0) return `ピークまで あと約${delta}人`;
  return recChip;
}

/**
 * リアルタイム人数の「鮮度」表示のしきい値（分）。
 * 最新実測がこの分数以上前なら「今の数値」とは見なさず、閉店中/計測停止として
 * 「最終 HH:MM 時点」の注記に切り替える。
 */
export const REALTIME_STALE_THRESHOLD_MIN = 20;

/**
 * リアルタイム人数の鮮度情報。
 * - `none`: latestActualTs が null/不正 → 鮮度表示は出さない（誤った「0分前」を避ける）。
 * - `fresh`: しきい値未満 → 「◯分前更新」（0分は「たった今更新」）。
 * - `stale`: しきい値以上 → 「最終 HH:MM 時点」（閉店中/計測停止の注記）。
 */
export type FreshnessInfo =
  | { state: "none" }
  | { state: "fresh"; minutesAgo: number; label: string }
  | { state: "stale"; minutesAgo: number; asOfLabel: string; label: string };

/**
 * 最新実測の ts と現在時刻から、リアルタイム人数の鮮度表示を決める純粋関数。
 * ts は絶対時刻（ISO）なので getTime() 差分で分数を出す（TZ非依存）。
 */
export function computeFreshness(
  latestActualTs: string | null | undefined,
  now: Date = new Date(),
  staleThresholdMin: number = REALTIME_STALE_THRESHOLD_MIN,
): FreshnessInfo {
  if (!latestActualTs) return { state: "none" };
  const t = new Date(latestActualTs);
  if (Number.isNaN(t.getTime())) return { state: "none" };
  // 未来の ts（端末時計のズレ）は 0 分前として扱う（負数を出さない）。
  const minutesAgo = Math.max(0, Math.floor((now.getTime() - t.getTime()) / 60_000));
  if (minutesAgo >= staleThresholdMin) {
    const asOfLabel = formatNowHmJst(t);
    return { state: "stale", minutesAgo, asOfLabel, label: `最終 ${asOfLabel} 時点` };
  }
  const label = minutesAgo === 0 ? "たった今更新" : `${minutesAgo}分前更新`;
  return { state: "fresh", minutesAgo, label };
}
