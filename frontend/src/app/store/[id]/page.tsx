import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  buildStoreBrandName,
  buildStoreFullName,
  buildStoreTitleName,
  getStoreMetaBySlugStrict,
  isPercentCrowdBrand,
  STORES,
  type StoreMeta,
} from "../../config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { buildPageMetadata } from "@/lib/seo/pageMetadata";
import { buildBreadcrumbList, buildNightClubJsonLd, serializeJsonLd } from "@/lib/jsonLd";
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
  pickLatestActualPoint,
  type StoreSnapshot,
} from "../../hooks/storePreviewSnapshot";
import {
  assembleStoreSnapshot,
  resolveLatestActualTs,
} from "@/lib/forecast/assembleSnapshot";
import {
  STORE_SNAPSHOT_TIMEOUT_MS,
  fetchBackendSnapshot,
} from "@/lib/serverSnapshot";
import StorePageClient from "./StorePageClient";
import Link from "next/link";
import { getAreaConfigForStoreSlug } from "@/app/config/areas";

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

/** タイムアウト/失敗時に一度だけ再試行するまでの待機時間 */
const SERVER_SNAPSHOT_RETRY_DELAY_MS = 400;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * ストアページの初回描画用スナップショットをサーバーで取得する。
 * useStorePreviewData の today モード・forecastRetryAttempt=0 のロジックと同じ純粋関数を
 * 再利用し、クライアント側の初回フェッチと同じ形のデータを組み立てる（ロジック重複を避ける）。
 *
 * Flask バックエンドを（lib/serverSnapshot の fetchBackendSnapshot で）直接叩く。
 * Next の /api/range 等の自前プロキシは経由しない。
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

    const rangePath =
      `/api/range?store=${encodeURIComponent(meta.slug)}` +
      `&from=${encodeURIComponent(fromYmd)}` +
      `&to=${encodeURIComponent(toYmd)}` +
      `&limit=${rangeLimit}`;
    // forecast_snapshot は完了済みの夜の不変データ（/api/forecast_snapshot の route.ts と
    // 同じ 86400s キャッシュ方針）。forecast_today は今まで通り 120s。
    const forecastPath = completedNight
      ? `/api/forecast_snapshot?store=${encodeURIComponent(meta.slug)}` +
        `&date=${encodeURIComponent(nightDateYYYYMMDD(baseDate))}`
      : `/api/forecast_today?store=${encodeURIComponent(meta.slug)}`;
    const forecastRevalidateSeconds = completedNight ? 86_400 : REVALIDATE_SECONDS;

    const [rangeJson, forecastJson] = await Promise.all([
      fetchBackendSnapshot<unknown>(rangePath, REVALIDATE_SECONDS, STORE_SNAPSHOT_TIMEOUT_MS),
      fetchBackendSnapshot<unknown>(
        forecastPath,
        forecastRevalidateSeconds,
        STORE_SNAPSHOT_TIMEOUT_MS,
      ),
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

      // 完了済みの夜は実測(実線)＋予測(点線)を overlayAllForecast:true で重ねているため、
      // 系列に予測点が併存する。ピークは実測点のみ（actualOnlyPeak:true）から算出し、予測点が
      // 「その夜のピーク」を上書きするのを防ぐ（useStorePreviewData の完了夜分岐と一致させる）。
      return assembleStoreSnapshot({
        base: baseSnapshot,
        series: effectiveSeries,
        latestActual,
        actualOnlyPeak: true,
        level: "データ取得済み",
        recommendation: "データ取得済み",
        // snapshot が無い/空（記録前の古い夜等）なら "--:--" のまま
        // （useStorePreviewData と同様、警告状態にはせず forecastStatus は idle のまま）。
        // 注: この2値の決め方は hook 側（合流できたら無条件に現在時刻＋"ok"）と意図的に異なる。
        forecastUpdatedLabel: snapshotPoints.length > 0 ? "更新済み" : "--:--",
        hasData,
        forecastStatus: snapshotPoints.length > 0 ? "ok" : "idle",
        latestActualTs: resolveLatestActualTs(latestActual, effectiveSeries),
        // この分岐は完了済みの夜（05:00-19:00 の間 or 過去日）のみ到達する。
        completedNight: true,
      });
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

    const forecastStatus: StoreSnapshot["forecastStatus"] = isInsufficientHistory
      ? "insufficient_history"
      : allForecastPoints.length > 0
        ? "ok"
        : "idle"; // 空の予測はクライアント側の再試行ループに委ねる（サーバーでは再試行しない）

    return assembleStoreSnapshot({
      base: baseSnapshot,
      series: effectiveSeries,
      latestActual,
      actualOnlyPeak: false,
      level: "データ取得済み",
      recommendation: "データ取得済み",
      forecastUpdatedLabel: allForecastPoints.length > 0 ? "更新済み" : "--:--",
      hasData,
      forecastStatus,
      latestActualTs: resolveLatestActualTs(latestActual, effectiveSeries),
      // ここは completedNight===false（進行中/これからの夜）のみ到達する。
      completedNight: false,
    });
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
  // モバイルSERPで実質切れる30〜35字の枠内に収めるため、<title>だけは空白無しの短縮表記を使う
  // （本文・JSON-LDの表記はスペースありの buildStoreFullName のまま変えない）。
  // ブランド名＋地名（=titleName自体）＋一般語「相席ラウンジ」の順で前半に並べる。
  const titleName = buildStoreTitleName(meta);
  const title = `${titleName}の混雑状況｜相席ラウンジの今夜の予測`;
  // 相席屋は人数非公開（%のみ）。オリエンタルは人数+男女比。実際にページで表示している値のみ書く。
  const metricLabel = isPercentCrowdBrand(meta.brand)
    ? "現在の混雑度（％）"
    : "現在の混雑人数・男女比";
  const description = `${meta.areaLabel}の相席ラウンジ「${fullName}」。${metricLabel}をリアルタイム表示し、AIが今夜のピーク時間を予測。来店前の下見にどうぞ。`;

  return buildPageMetadata({
    title,
    description,
    path: `/store/${encodeURIComponent(meta.slug)}`,
  });
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

  const breadcrumb = buildBreadcrumbList([
    { name: "ホーム", item: homeUrl },
    { name: "店舗一覧", item: storesUrl },
    { name: fullName, item: storeUrl },
  ]);

  // addressCountry の判定・areaServed の組み立ては buildNightClubJsonLd 側に一本化済み
  // （海外(韓国・江南)店のみ KR、それ以外は JP）。brandName は同じ meta から作るため、
  // ブランドを混同する余地がない。
  const localBusiness = buildNightClubJsonLd({
    name: fullName,
    url: storeUrl,
    regionLabel: meta.regionLabel,
    areaLabel: meta.areaLabel,
    lat: meta.lat,
    lon: meta.lon,
    brandName: buildStoreBrandName(meta),
  });

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

      {/*
        SSR の内部リンク: /store/[id] の静的HTMLは h1 + Suspense fallback だけで、
        「ほかの店舗」「エリア一覧」への実アンカーはクライアント描画後にしか出ない。
        クローラが読む raw HTML にエリアハブ（/area/{id}）と全店舗一覧への導線を1行だけ載せる
        （SEO Phase2 の /stores AllStoresSsrNav と同じ考え方）。エリア未設定の店舗は一覧のみ。
      */}
      <StoreAreaSsrNav slug={meta.slug} />
    </>
  );
}

function StoreAreaSsrNav({ slug }: { slug: string }) {
  const area = getAreaConfigForStoreSlug(slug);
  return (
    <nav
      aria-label="エリア・店舗一覧へ"
      className="mx-auto mt-6 flex w-full max-w-6xl flex-wrap gap-x-4 gap-y-2 px-4 pb-8 text-xs"
    >
      {area && (
        <Link
          href={`/area/${encodeURIComponent(area.id)}`}
          className="text-indigo-300 underline decoration-indigo-300/30 underline-offset-2 hover:text-indigo-200"
        >
          {area.displayName}の相席ラウンジ一覧 →
        </Link>
      )}
      <Link
        href="/stores"
        className="text-slate-400 underline decoration-white/20 underline-offset-2 hover:text-slate-200"
      >
        全店舗の混雑状況一覧 →
      </Link>
    </nav>
  );
}
