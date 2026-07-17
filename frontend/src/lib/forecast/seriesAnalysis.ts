// frontend/src/lib/forecast/seriesAnalysis.ts
//
// 時系列（実測/予測）の組み立て・ピーク検出・鮮度分析だけを集めたモジュール。
// React import は一切含まない。
//
// 経緯: これらの関数はもともと frontend/src/app/hooks/storePreviewSnapshot.ts に
// 「日付/JST/夜窓」「スナップショット組み立て」と同居していたが、実体は app/hooks
// （クライアントフック層）に依存しない汎用の系列分析ユーティリティだったため、
// components からの参照が components → app/hooks という逆転依存を生んでいた。
// ロジックを変更せず本モジュールへ機械的に移設する
// （storePreviewSnapshot.ts は re-export バレルとしてこれらを再公開する）。
import { isPercentCrowdBrand, seatFullnessPercent } from "@/app/config/stores";
import { formatNowHmJst } from "@/lib/date/nightWindow";
import type {
  ForecastPoint,
  RangePoint,
  StoreSnapshot,
  TimeSeriesPoint,
} from "@/app/hooks/storePreviewSnapshot";

function formatLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit" });
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

/**
 * ピーク（最も混雑した系列点）を求める。
 *
 * `options.actualOnly`（既定 false）:
 * - false（進行中の夜）: 従来どおり actual を優先し、無ければ forecast を使う。
 *   進行中の today モードでは「予測ピーク＝今夜これから来る想定ピーク」を出すのが意図なので
 *   forecast 点も含める。
 * - true（完了済みの夜の答え合わせ）: 実測点（menActual/womenActual が非 null）だけを対象に
 *   ピークを算出する。完了夜のオーバーレイ（overlayAllForecast=true）では実測（秒粒度 ts）と
 *   予測（15分グリッド ts）が別キーで併存するため、実測ピークより高い予測点が「表示ピーク」に
 *   化ける不具合を防ぐ（例: shibuya 実測202 → 予測220で+35分ズレ）。
 */
export function pickPeak(
  series: TimeSeriesPoint[],
  options: { actualOnly?: boolean } = {},
) {
  const actualOnly = options.actualOnly ?? false;
  let bestLabel = "";
  let bestTs: string | null = null;
  let bestTotal = 0;
  let bestMen: number | null = null;
  let bestWomen: number | null = null;
  series.forEach((p) => {
    // 完了夜の答え合わせでは実測点のみを対象にする（予測点は無視）。
    if (actualOnly && p.menActual === null && p.womenActual === null) return;
    // actual があればそちらを優先、なければ forecast（二重カウント防止）。
    // actualOnly の場合は forecast へフォールバックせず実測値だけで総数を出す。
    const men = actualOnly ? p.menActual ?? 0 : p.menActual ?? p.menForecast ?? 0;
    const women = actualOnly ? p.womenActual ?? 0 : p.womenActual ?? p.womenForecast ?? 0;
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
 * 混雑度（目安）チップの中身（rank3 バグ修正）。
 *
 * バグ: `nowTotal` は latestActualTs（夜窓フィルタ前の全レンジ内の最新実測点）優先で
 * 計算される「今まさにの人数」であるのに対し、`peakTotal` は選択中の夜（昨日/先週/
 * カスタム＝過去の完了済みの夜）だけに絞ったピークになる。完了夜タブを見ているのに
 * 分子だけ「今夜のリアルタイム人数」のままだと、無関係な値同士の比率になり
 * 「ピーク比480%」のような無意味な数字と誤った混雑ラベルが出る
 * （例: shibuya 199÷71=280%、ay_ueno 48÷10=480%）。
 *
 * 修正: 完了済みの夜（completedNight）ではチップ自体を出さない（null を返す）。
 * 進行中（今夜ライブ）の自店ピーク比としてのみ意味を持つため、それ以外は非表示にする。
 */
export function crowdHintChip(
  snapshot: Pick<StoreSnapshot, "completedNight" | "nowTotal" | "peakTotal">,
): { crowd: string; occupancyPercent: number | null } | null {
  if (snapshot.completedNight) return null;
  const total = Math.max(0, Math.round(Number(snapshot.nowTotal ?? 0)));
  const peak = Math.max(0, Math.round(Number(snapshot.peakTotal ?? 0)));
  const crowd = crowdHintFromTotals(total, peak);
  const occupancyPercent = peak > 0 ? Math.round((total / peak) * 100) : null;
  return { crowd, occupancyPercent };
}

function crowdHintFromTotals(nowTotal: number, peakTotal: number): string {
  if (peakTotal <= 0) return "予測データ待ち";
  const r = nowTotal / peakTotal;
  if (r >= 0.85) return "混雑に近い目安";
  if (r >= 0.45) return "ほどよい目安";
  return "空いている目安";
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
