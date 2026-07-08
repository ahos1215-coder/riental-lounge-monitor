import { cache } from "react";
import type { Metadata } from "next";
import { buildStoreFullName, getStoreMetaBySlugStrict, STORES, type StoreMeta } from "../../config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { serializeJsonLd } from "@/lib/jsonLd";
import {
  RANGE_LIMIT_BY_MODE,
  buildBaseSnapshot,
  buildSeries,
  computeNightBaseDate,
  computeNightWindowFromBaseDate,
  formatYMD,
  addDays,
  hasSeriesData,
  isWithinNight,
  parseForecastPoints,
  parseRangePoints,
  pickCurrentActual,
  pickLatestActualPoint,
  pickPeak,
  type StoreSnapshot,
} from "../../hooks/storePreviewSnapshot";
import StorePageClient from "./StorePageClient";

type Props = {
  params: Promise<{ id: string }>;
};

/** 毎日18:00/21:30更新のレポートとは別に、実測+予測は数分単位で動くため短め */
export const revalidate = 120;

/** dynamicParams はデフォルト true のまま（新店舗追加時にビルドし直さなくても動く） */

/** ビルド時に全店舗ページを静的生成する（44店） */
export function generateStaticParams(): { id: string }[] {
  return STORES.map((s) => ({ id: s.slug }));
}

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/**
 * サーバー側の初回スナップショット取得タイムアウト。Render 等のコールドスタート時に
 * ISR の再生成コストを一定時間で打ち切るための安全弁。超過/失敗時は null を返し、
 * StorePageClient 側は initialSnapshot 無しの通常 CSR フローにフォールバックする。
 *
 * ISR の再生成はバックグラウンドの stale-while-revalidate であり、訪問者のレスポンスを
 * ブロックしない（再生成が遅くても既存キャッシュが即返る）。一方 initialSnapshot が null に
 * なった場合の代償（クライアント側でコールドウォーターフォール全部を踏む）の方がはるかに大きい
 * ため、多少再生成が遅くなってもタイムアウトは長めに倒す。
 */
const SERVER_SNAPSHOT_TIMEOUT_MS = 5_000;

/** タイムアウト/失敗時に一度だけ再試行するまでの待機時間 */
const SERVER_SNAPSHOT_RETRY_DELAY_MS = 400;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJsonWithTimeout(url: string, timeoutMs: number): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      next: { revalidate: 120 },
    });
    if (!res.ok) return null;
    return await res.json().catch(() => null);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * ストアページの初回描画用スナップショットをサーバーで取得する。
 * useStorePreviewData の today モード・forecastRetryAttempt=0 のロジックと同じ純粋関数を
 * 再利用し、クライアント側の初回フェッチと同じ形のデータを組み立てる（ロジック重複を避ける）。
 *
 * Flask バックエンドを BACKEND_URL から直接叩く（/api/range 等の自前プロキシを経由しない）。
 * 理由: サーバーコンポーネントから自分自身の /api ルートを絶対URLで叩く自己参照フェッチは、
 * サーバーレス環境でコールドスタート同士が重なる/ビルド時にサーバーが存在しない等で
 * 不安定・低速になりやすい。/api/range・/api/forecast_today も内部で同じ BACKEND_URL に対して
 * 同じ `next.revalidate` 付き fetch をしているだけなので、直接叩いても Next Data Cache への
 * 参加や挙動は変わらない。
 *
 * 失敗・タイムアウト時は null を返す（呼び出し側は今日通りの CSR 挙動にフォールバックする）。
 */
async function fetchInitialSnapshotOnce(meta: StoreMeta): Promise<StoreSnapshot | null> {
  try {
    const base = BACKEND_URL.replace(/\/+$/, "");
    const now = new Date();
    const baseDate = computeNightBaseDate(now);
    const nightWindow = computeNightWindowFromBaseDate(baseDate);
    const rangeLimit = RANGE_LIMIT_BY_MODE.today;
    const fromYmd = formatYMD(baseDate);
    const toYmd = formatYMD(addDays(baseDate, 1));

    const rangeUrl =
      `${base}/api/range?store=${encodeURIComponent(meta.slug)}` +
      `&from=${encodeURIComponent(fromYmd)}` +
      `&to=${encodeURIComponent(toYmd)}` +
      `&limit=${rangeLimit}`;
    const forecastUrl = `${base}/api/forecast_today?store=${encodeURIComponent(meta.slug)}`;

    const [rangeJson, forecastJson] = await Promise.all([
      fetchJsonWithTimeout(rangeUrl, SERVER_SNAPSHOT_TIMEOUT_MS),
      fetchJsonWithTimeout(forecastUrl, SERVER_SNAPSHOT_TIMEOUT_MS),
    ]);

    const baseSnapshot = buildBaseSnapshot(meta);

    const allRangePoints = parseRangePoints(rangeJson);
    const rangePoints = allRangePoints.filter((p) => isWithinNight(p.ts, nightWindow));
    const latestActual = pickLatestActualPoint(allRangePoints);

    // insufficient_history の場合、forecast はダミー行のみなので予測系列には使わない
    // （useStorePreviewData と同じ扱い: 実測のみ表示、予測は "insufficient_history" 状態）。
    const isInsufficientHistory = Boolean(
      (forecastJson as { insufficient_history?: boolean } | null)?.insufficient_history,
    );
    const allForecastPoints = isInsufficientHistory ? [] : parseForecastPoints(forecastJson);
    const forecastPoints = allForecastPoints.filter((p) => isWithinNight(p.ts, nightWindow));

    const series = buildSeries(rangePoints, forecastPoints);
    const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
    const hasData = hasSeriesData(series) || latestActual !== null;

    // データが何も無ければ「取得はできたが空」であり、CSR 側の baseSnapshot と実質同じ。
    // その場合はわざわざ initialSnapshot を渡さず、null にして通常の CSR フローに任せる。
    if (!hasData) return null;

    const current = pickCurrentActual(effectiveSeries);
    const nowMen = latestActual?.nowMen ?? current.nowMen;
    const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
    const { peakTotal, peakTimeLabel, peakMen, peakWomen } = pickPeak(effectiveSeries);
    const latestActualTs =
      latestActual?.ts ??
      [...effectiveSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
      null;

    const forecastStatus: StoreSnapshot["forecastStatus"] = isInsufficientHistory
      ? "insufficient_history"
      : allForecastPoints.length > 0
        ? "ok"
        : "idle"; // 空の予測はクライアント側の再試行ループに委ねる（サーバーでは再試行しない）

    const snapshot: StoreSnapshot = {
      ...baseSnapshot,
      level: "データ取得済み",
      recommendation: "データ取得済み",
      nowMen: Math.round(nowMen),
      nowWomen: Math.round(nowWomen),
      nowTotal: Math.round(nowMen + nowWomen),
      peakTotal: Math.round(peakTotal),
      peakTimeLabel,
      peakMen,
      peakWomen,
      forecastUpdatedLabel: allForecastPoints.length > 0 ? "更新済み" : "--:--",
      series: effectiveSeries,
      hasData,
      forecastStatus,
      latestActualTs,
    };
    return snapshot;
  } catch {
    // 予期しない例外もフェイルセーフ。initialSnapshot 無しの CSR にフォールバックする。
    return null;
  }
}

/**
 * fetchInitialSnapshotOnce の結果が null（タイムアウト/データ無し/失敗）だった場合、
 * 短い待機を挟んで一度だけ再試行する。ISR 再生成の背後にあるバックエンドの一時的な混雑
 * （同時発火した range/forecast_today が gunicorn のワーカーキューに詰まっている等）は
 * 数百ms で解消することが多く、1回だけの再試行で initialSnapshot が null になる確率を
 * 大きく下げられる。再試行分の AbortController は新規に張り直す（初回のものを使い回さない）。
 */
async function fetchInitialSnapshot(meta: StoreMeta): Promise<StoreSnapshot | null> {
  const first = await fetchInitialSnapshotOnce(meta);
  if (first) return first;
  await delay(SERVER_SNAPSHOT_RETRY_DELAY_MS);
  return fetchInitialSnapshotOnce(meta);
}

/**
 * generateMetadata と本体（StorePage）の両方で店舗メタは使うが store 情報自体は同期的なので
 * cache() は不要。initialSnapshot の取得だけ cache() で包み、同一リクエスト内での重複フェッチを防ぐ
 * （このページでは generateMetadata 側は initialSnapshot を使わないため、実質的に本体の1回だけ
 * 呼ばれるが、将来 generateMetadata が使うようになっても二重フェッチしないよう安全側に倒す）。
 */
const resolveInitialSnapshot = cache(async (slug: string): Promise<StoreSnapshot | null> => {
  const meta = getStoreMetaBySlugStrict(slug);
  if (!meta) return null;
  return fetchInitialSnapshot(meta);
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const meta = getStoreMetaBySlugStrict(id);
  if (!meta) return {};

  const fullName = buildStoreFullName(meta);
  const title = `${fullName}（${meta.areaLabel}）の混雑状況・今夜の混雑予測`;
  const description = `${fullName}の現在の混雑・男女比をリアルタイム表示。AIが今夜の混雑ピークを時間帯別に予測。毎日18:00と21:30にレポート更新。${meta.regionLabel}エリアで相席するならデータでチェック。`;
  const base = getMetadataBaseUrl();
  const url = new URL(`/store/${encodeURIComponent(meta.slug)}`, base);

  return {
    title,
    description,
    alternates: { canonical: url.href },
    openGraph: {
      title,
      description,
      url,
      type: "website",
      locale: "ja_JP",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function StorePage({ params }: Props) {
  const { id } = await params;
  const meta = getStoreMetaBySlugStrict(id);

  let jsonLd: string | null = null;
  if (meta) {
    const fullName = buildStoreFullName(meta);
    const base = getMetadataBaseUrl();
    const storeUrl = new URL(`/store/${encodeURIComponent(meta.slug)}`, base).href;
    const homeUrl = base.href.replace(/\/+$/, "") || base.href;
    const storesUrl = new URL("/stores", base).href;

    const breadcrumb = {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "ホーム", item: homeUrl },
        { "@type": "ListItem", position: 2, name: "店舗一覧", item: storesUrl },
        { "@type": "ListItem", position: 3, name: fullName, item: storeUrl },
      ],
    };

    const localBusiness: Record<string, unknown> = {
      "@context": "https://schema.org",
      "@type": "NightClub",
      name: fullName,
      address: {
        "@type": "PostalAddress",
        addressRegion: meta.regionLabel,
        addressLocality: meta.areaLabel,
        addressCountry: "JP",
      },
      url: storeUrl,
    };
    if (meta.lat != null && meta.lon != null) {
      localBusiness.geo = {
        "@type": "GeoCoordinates",
        latitude: meta.lat,
        longitude: meta.lon,
      };
    }

    jsonLd = serializeJsonLd([breadcrumb, localBusiness]);
  }

  // 不正な slug は StorePageClient 側（useEffect）で /stores へリダイレクトする既存挙動を
  // 維持するため、ここでは notFound() にせず initialSnapshot=null のまま描画を続ける。
  const initialSnapshot = meta ? await resolveInitialSnapshot(meta.slug) : null;

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      )}
      {meta && (
        <h1 className="mx-auto w-full max-w-6xl px-4 pt-6 text-lg font-semibold text-slate-100 md:text-xl">
          {buildStoreFullName(meta)}の混雑状況
        </h1>
      )}
      <StorePageClient initialSnapshot={initialSnapshot} />
    </>
  );
}
