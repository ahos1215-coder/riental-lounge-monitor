import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  buildStoreFullName,
  getStoreMetaBySlugStrict,
  STORES,
  type StoreMeta,
} from "../../config/stores";
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
  isNightCompleted,
  isWithinNight,
  nightDateYYYYMMDD,
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

/**
 * 毎日18:00/21:30更新のレポートとは別に、実測+予測は数分単位で動くため短め。
 * Next.js の revalidate route segment config は静的解析専用のため、ここは定数参照ではなく
 * リテラルのままにする必要がある（下の REVALIDATE_SECONDS と値は同じ 120 で揃える）。
 */
export const revalidate = 120;
/** 上の revalidate と同じ値（120秒）。リテラル export にできない他の箇所で使う共有定数。 */
const REVALIDATE_SECONDS = 120;

/**
 * dynamicParams=false に変更（旧: デフォルト true のまま「新店舗追加時にビルドし直さなくても
 * 動く」ことを優先していた）。
 *
 * 理由: dynamicParams=true だと、generateStaticParams に無い slug（存在しない店舗・typo等）への
 * アクセス時、Next の ISR フォールバック生成パスを通り notFound() を呼んでも HTTP ステータスが
 * 200 に固定される（Next.js の既知の挙動: fallback 生成中に一部HTMLがflushされるとstatusが
 * ロックされる）。これはソフト404そのものであり、SEO Phase2 の目的（クロールされる無効slugを
 * 正しく404化する）と正面から矛盾する。
 *
 * 一方「新店舗が次回デプロイ前でも即表示される」という dynamicParams=true の利点は、
 * stores.json 自体がリポジトリにコミットされる静的データ（=変更には常にデプロイが伴う）である
 * ため実質的に発生しない。よって real 404 を優先し dynamicParams=false に倒す。
 * 新店舗追加時は stores.json 更新 → デプロイで generateStaticParams が再実行され反映される
 * （既存の運用フローと同じ）。
 */
export const dynamicParams = false;

/** ビルド時に全店舗ページを静的生成する（42店。ol_sapporo_ag は 2026-07-11 閉店で除外） */
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

async function fetchJsonWithTimeout(
  url: string,
  timeoutMs: number,
  revalidateSeconds = REVALIDATE_SECONDS,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      next: { revalidate: revalidateSeconds },
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
 * 完了済みの夜（05:00-19:00 の間、または対象の夜が既に終わっている場合）は
 * useStorePreviewData の completedNight 分岐と全く同じ判定・URL 形式・マージ方法
 * （実測 + /api/forecast_snapshot を overlayAllForecast:true でマージ）を使う。
 * これにより、昼間の ISR 再生成が重い ML 計算（forecast_today）を一切呼ばずに済み、
 * かつクライアントが実際に表示する「完了済みの夜の答え合わせ」と同じ実データを
 * そのまま HTML に焼き込める（従来は forecast_today の結果をクライアントが使わないまま
 * 二重に計算していた上、データが無ければ initialSnapshot が null になり空箱 HTML になっていた）。
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
    // 「今日」の夜が既に終わっている（05:00-19:00 の間）かどうか。true の場合、
    // useStorePreviewData と同じく forecast_today (重い ML 計算) を呼ばず、
    // その夜に配信済みだった forecast_snapshot を使う。
    const completedNight = isNightCompleted(baseDate, now);

    const rangeUrl =
      `${base}/api/range?store=${encodeURIComponent(meta.slug)}` +
      `&from=${encodeURIComponent(fromYmd)}` +
      `&to=${encodeURIComponent(toYmd)}` +
      `&limit=${rangeLimit}`;
    // forecast_snapshot は完了済みの夜の不変データ（/api/forecast_snapshot の route.ts と
    // 同じ 86400s キャッシュ方針）。forecast_today は今まで通り 120s。
    const forecastUrl = completedNight
      ? `${base}/api/forecast_snapshot?store=${encodeURIComponent(meta.slug)}` +
        `&date=${encodeURIComponent(nightDateYYYYMMDD(baseDate))}`
      : `${base}/api/forecast_today?store=${encodeURIComponent(meta.slug)}`;
    const forecastRevalidateSeconds = completedNight ? 86_400 : REVALIDATE_SECONDS;

    const [rangeJson, forecastJson] = await Promise.all([
      fetchJsonWithTimeout(rangeUrl, SERVER_SNAPSHOT_TIMEOUT_MS),
      fetchJsonWithTimeout(forecastUrl, SERVER_SNAPSHOT_TIMEOUT_MS, forecastRevalidateSeconds),
    ]);

    const baseSnapshot = buildBaseSnapshot(meta);

    const allRangePoints = parseRangePoints(rangeJson);
    const rangePoints = allRangePoints.filter((p) => isWithinNight(p.ts, nightWindow));
    const latestActual = pickLatestActualPoint(allRangePoints);

    if (completedNight) {
      // 完了済みの夜: useStorePreviewData の completedNight 分岐と同じ組み立て
      // （実測 + forecast_snapshot を overlayAllForecast:true でマージ）。
      const snapshotOk = Boolean((forecastJson as { ok?: boolean } | null)?.ok);
      const allSnapshotPoints = snapshotOk ? parseForecastPoints(forecastJson) : [];
      const snapshotPoints = allSnapshotPoints.filter((p) => isWithinNight(p.ts, nightWindow));

      const series = buildSeries(rangePoints, snapshotPoints, true);
      const effectiveSeries = series.length > 0 ? series : baseSnapshot.series;
      const hasData = hasSeriesData(series) || latestActual !== null;

      // データが何も無ければ「取得はできたが空」であり、CSR 側の baseSnapshot と実質同じ。
      // その場合はわざわざ initialSnapshot を渡さず、null にして通常の CSR フローに任せる。
      if (!hasData) return null;

      const current = pickCurrentActual(effectiveSeries);
      const nowMen = latestActual?.nowMen ?? current.nowMen;
      const nowWomen = latestActual?.nowWomen ?? current.nowWomen;
      // 完了済みの夜は実測(実線)＋予測(点線)を overlayAllForecast:true で重ねているため、
      // 系列に予測点が併存する。ピークは実測点のみから算出し、予測点が「その夜のピーク」を
      // 上書きするのを防ぐ（useStorePreviewData の完了夜分岐と一致させる）。
      const { peakTotal, peakTimeLabel, peakTs, peakMen, peakWomen } = pickPeak(effectiveSeries, {
        actualOnly: true,
      });
      const latestActualTs =
        latestActual?.ts ??
        [...effectiveSeries].reverse().find((p) => p.menActual !== null || p.womenActual !== null)?.ts ??
        null;

      const snapshot: StoreSnapshot = {
        ...baseSnapshot,
        level: "データ取得済み",
        recommendation: "データ取得済み",
        nowMen: Math.round(nowMen),
        nowWomen: Math.round(nowWomen),
        nowTotal: Math.round(nowMen + nowWomen),
        peakTotal: Math.round(peakTotal),
        peakTimeLabel,
        peakTs,
        peakMen,
        peakWomen,
        // snapshot が無い/空（記録前の古い夜等）なら "--:--" のまま
        // （useStorePreviewData と同様、警告状態にはせず forecastStatus は idle のまま）。
        forecastUpdatedLabel: snapshotPoints.length > 0 ? "更新済み" : "--:--",
        series: effectiveSeries,
        hasData,
        forecastStatus: snapshotPoints.length > 0 ? "ok" : "idle",
        latestActualTs,
        // この分岐は完了済みの夜（05:00-19:00 の間 or 過去日）のみ到達する。
        completedNight: true,
      };
      return snapshot;
    }

    // 進行中/これからの夜: 従来通り forecast_today（未来区間のみ点線）
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
    const { peakTotal, peakTimeLabel, peakTs, peakMen, peakWomen } = pickPeak(effectiveSeries);
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
      peakTs,
      peakMen,
      peakWomen,
      forecastUpdatedLabel: allForecastPoints.length > 0 ? "更新済み" : "--:--",
      series: effectiveSeries,
      hasData,
      forecastStatus,
      latestActualTs,
      // ここは completedNight===false（進行中/これからの夜）のみ到達する。
      completedNight: false,
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
  if (!meta) notFound();

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
  if (!meta) notFound();

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
      // 海外(韓国・江南)店のみ KR。それ以外は国内 JP。構造化データの国情報を実体に一致させる。
      addressCountry:
        meta.regionLabel === "海外" && meta.areaLabel.includes("韓国") ? "KR" : "JP",
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

  const jsonLd = serializeJsonLd([breadcrumb, localBusiness]);

  const initialSnapshot = await resolveInitialSnapshot(meta.slug);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd }}
      />
      <h1 className="mx-auto w-full max-w-6xl px-4 pt-6 text-lg font-semibold text-slate-100 md:text-xl">
        {fullName}の混雑状況
      </h1>

      <StorePageClient initialSnapshot={initialSnapshot} />
    </>
  );
}
