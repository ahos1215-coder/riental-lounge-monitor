// frontend/src/lib/store/ssrSummary.ts
//
// 店舗詳細ページの「サーバー側HTMLに実データのテキストを出す」ための純粋関数。
//
// 背景（SEO班B）: /store/[id] の静的HTMLは本文テキストが 127 文字しか無く、その中で店舗ごとに
// 異なるのは <h1> の店舗名だけだった（残りはヘッダー/フッターの共通文言）。原因は
//   1. StorePageInner / MeguribiDashboardPreview が useSearchParams() を使うため、静的プリレンダ時に
//      直近の <Suspense> 境界が CSR へ bail し、HTML には StorePageFallback（スケルトン）しか出ない
//   2. さらに内側の PreviewMainSection は dynamic(ssr:false)
// の2段構え。initialSnapshot（page.tsx がサーバーで取得済みの実データ）自体は HTML に入っているが、
// RSC の flight payload（<script>タグの中）にしか無いため、クローラはテキストとして読めない。
//
// そこで「既に画面に出ている実データ」を Suspense の fallback（＝静的HTMLに載る唯一の場所）で
// テキストとして描画する。fallback はハイドレーション後に本物のダッシュボードへ差し替わるので、
// 利用者が最終的に見る画面は変わらない。ここは その fallback が使う値の組み立てだけを担う
// 純粋関数（React 非依存・node環境でテスト可能）。
//
// 厳守事項:
//  - 実データのみ。無い値は出さない（0人・--:-- 等の「空箱」を作らない）
//  - 相席屋（isPercentCrowdBrand）は在店人数を公開していないため、人数は一切出さず % のみ
//  - 時刻は JST 絶対時刻（「◯分前」は生成時刻に依存し ISR で嘘になるため使わない）
import {
  isPercentCrowdBrand,
  seatFullnessPercent,
  seatFullnessPercentOfTotal,
} from "@/app/config/stores";
import type { StoreSnapshot, TimeSeriesPoint } from "@/lib/forecast/types";
import { toNonNegIntOrNull } from "@/lib/range/rangeRows";
import { MIN_HOURLY_BUCKETS, rollUpByNightHour } from "./nightHourlyRollup";
import { formatNowHmJst } from "@/lib/date/nightWindow";

/** peakTimeLabel / forecastUpdatedLabel が「値なし」を表すときのプレースホルダ */
const PLACEHOLDER_TIME_LABELS = new Set(["", "-", "—", "--:--", "–"]);

// 時間帯別ロールアップと最小バケット数は lib/store/nightHourlyRollup.ts が正本
// （エリアページ areaLiveSummary.ts と共有）。

export type SsrStat = {
  /** 「男性」「女性」など */
  label: string;
  /** 「18人」「40%」など単位込みの表示文字列 */
  value: string;
};

export type StoreSsrSummaryData = {
  /** 「オリエンタルラウンジ 大宮」など（snapshot.name＝buildStoreFullName 済み） */
  storeName: string;
  /** 「大宮」など */
  areaLabel: string;
  /** 「店内の目安」/「店内の埋まり具合」。出せない場合は null */
  occupancyLabel: string | null;
  /** 「40名」/「約35%」。出せない場合は null */
  occupancyValue: string | null;
  /** 男性・女性の現在値。相席屋は必ず % のみ（人数を出さない） */
  genderStats: SsrStat[];
  /** 「男45% / 女55%」。人数合計が 0 なら null */
  ratioText: string | null;
  /** 「22:15（男性30名 / 女性28名）」。ピーク不明なら null */
  peakText: string | null;
  /** 「23:45 時点」。最新実測 ts が無ければ null */
  updatedText: string | null;
  /** 時間帯別の実測（19時／20時…）。2時間分未満なら空配列 */
  hourly: SsrStat[];
};

/** 系列値（number|null）の非負整数化。値なしは 0 として扱う（SSR テキストは 0 人と書ける）。 */
function toNonNegativeInt(value: number | null | undefined): number {
  return toNonNegIntOrNull(value) ?? 0;
}

function isMeaningfulTimeLabel(raw: string | null | undefined): boolean {
  const s = (raw ?? "").trim();
  return s.length > 0 && !PLACEHOLDER_TIME_LABELS.has(s);
}

/**
 * 実測点だけを「時」でまとめ、その時間帯の最大値を代表値にする。
 * label は buildSeries が JST の "HH:MM" で作っているので先頭2文字が時。
 */
export function rollUpHourlyActuals(
  series: readonly TimeSeriesPoint[],
): { hour: string; total: number }[] {
  const points: { hour: number; total: number }[] = [];
  for (const p of series) {
    if (p.menActual === null && p.womenActual === null) continue;
    const m = /^(\d{2}):\d{2}$/.exec(p.label ?? "");
    if (!m) continue;
    points.push({
      hour: Number(m[1]),
      total: toNonNegativeInt(p.menActual ?? 0) + toNonNegativeInt(p.womenActual ?? 0),
    });
  }
  // 集計（時ごとの最大・夜順）は共通化。hour は従来どおり "19"/"00" の2桁文字列で返す。
  return rollUpByNightHour(points).map(({ hour, total }) => ({
    hour: String(hour).padStart(2, "0"),
    total,
  }));
}

/**
 * initialSnapshot（サーバーで取得済みの実データ）から、HTMLにテキストとして出す値を組み立てる。
 * 実データが無い/取れなかった場合は null を返す（＝呼び出し側は従来どおりスケルトンのまま）。
 */
export function buildStoreSsrSummary(
  snapshot: StoreSnapshot | null | undefined,
): StoreSsrSummaryData | null {
  if (!snapshot || !snapshot.hasData) return null;

  const men = toNonNegativeInt(snapshot.nowMen);
  const women = toNonNegativeInt(snapshot.nowWomen);
  const total = Math.max(toNonNegativeInt(snapshot.nowTotal), 0) || men + women;

  // 相席屋は在店人数を公開していない。逆算推定の人数は内部値なので、表示は % のみ。
  const percentMode = isPercentCrowdBrand(snapshot.brand) && !!snapshot.capacity;
  const capacity = snapshot.capacity ?? 0;

  let occupancyLabel: string | null = null;
  let occupancyValue: string | null = null;
  const genderStats: SsrStat[] = [];

  if (percentMode) {
    const overallPct = seatFullnessPercentOfTotal(total, capacity);
    if (total > 0 && overallPct !== null) {
      occupancyLabel = "店内の埋まり具合";
      occupancyValue = `約${overallPct}%`;
    }
    const menPct = seatFullnessPercent(men, capacity);
    const womenPct = seatFullnessPercent(women, capacity);
    if (total > 0 && menPct !== null) genderStats.push({ label: "男性", value: `${menPct}%` });
    if (total > 0 && womenPct !== null) genderStats.push({ label: "女性", value: `${womenPct}%` });
  } else {
    if (total > 0) {
      occupancyLabel = "店内の目安";
      occupancyValue = `${total}名`;
      genderStats.push({ label: "男性", value: `${men}人` });
      genderStats.push({ label: "女性", value: `${women}人` });
    }
  }

  // 男女比は「比率」であって在店人数ではないため、相席屋でも既存カードと同じく表示する。
  const ratioText =
    total > 0
      ? `男${Math.round((men / total) * 100)}% / 女${Math.round((women / total) * 100)}%`
      : null;

  // ピーク目安。LatestForecastSummaryCard の mlHighlightChips と同じ値・同じ言い回しに揃える。
  let peakText: string | null = null;
  const peakTime = (snapshot.peakTimeLabel ?? "").trim();
  const peakTotal = toNonNegativeInt(snapshot.peakTotal);
  if (isMeaningfulTimeLabel(peakTime)) {
    if (peakTotal > 0) {
      if (percentMode) {
        const pm =
          snapshot.peakMen != null ? seatFullnessPercent(Math.round(snapshot.peakMen), capacity) : null;
        const pw =
          snapshot.peakWomen != null
            ? seatFullnessPercent(Math.round(snapshot.peakWomen), capacity)
            : null;
        const detail =
          pm != null || pw != null
            ? `男性${pm ?? 0}% / 女性${pw ?? 0}%`
            : `最大 席埋まり 約${seatFullnessPercentOfTotal(peakTotal, capacity) ?? 0}%`;
        peakText = `${peakTime}（${detail}）`;
      } else {
        const pm = snapshot.peakMen != null ? Math.round(snapshot.peakMen) : null;
        const pw = snapshot.peakWomen != null ? Math.round(snapshot.peakWomen) : null;
        const detail =
          pm != null || pw != null ? `男性${pm ?? 0}名 / 女性${pw ?? 0}名` : `最大 ${peakTotal}人`;
        peakText = `${peakTime}（${detail}）`;
      }
    } else {
      peakText = peakTime;
    }
  }

  // 「◯分前更新」は描画時刻に依存し、ISR で焼かれた HTML では嘘になる。JST の絶対時刻で出す。
  let updatedText: string | null = null;
  if (snapshot.latestActualTs) {
    const d = new Date(snapshot.latestActualTs);
    if (!Number.isNaN(d.getTime())) updatedText = `${formatNowHmJst(d)} 時点`;
  }

  const buckets = rollUpHourlyActuals(snapshot.series ?? []);
  const hourly: SsrStat[] =
    buckets.length >= MIN_HOURLY_BUCKETS
      ? buckets
          .map(({ hour, total: t }) => {
            if (percentMode) {
              const pct = seatFullnessPercentOfTotal(t, capacity);
              return pct === null ? null : { label: `${Number(hour)}時`, value: `約${pct}%` };
            }
            return { label: `${Number(hour)}時`, value: `${t}人` };
          })
          .filter((x): x is SsrStat => x !== null)
      : [];

  // 出せる実データが一つも無ければ「空箱」を作らない。
  const hasAnything =
    occupancyValue !== null ||
    genderStats.length > 0 ||
    peakText !== null ||
    hourly.length > 0;
  if (!hasAnything) return null;

  return {
    storeName: snapshot.name,
    areaLabel: snapshot.area,
    occupancyLabel,
    occupancyValue,
    genderStats,
    ratioText,
    peakText,
    updatedText,
    hourly,
  };
}
