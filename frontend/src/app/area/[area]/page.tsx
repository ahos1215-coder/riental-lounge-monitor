import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  AREAS,
  getAreaConfig,
  getAreaStores,
  type AreaConfig,
} from "@/app/config/areas";
import {
  buildStoreBrandName,
  buildStoreFullName,
  isPercentCrowdBrand,
  type StoreMeta,
} from "@/app/config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { fetchBackendSnapshot } from "@/lib/serverSnapshot";
import { STORE_CARD_RANGE_LIMIT, parseRangeResponse } from "@/lib/storeCardRangeSparkline";
import { buildAreaLiveSummary, type AreaLiveSummary } from "@/lib/area/areaLiveSummary";
import {
  buildAreaCollectionPageJsonLd,
  buildBreadcrumbList,
  serializeJsonLd,
} from "@/lib/jsonLd";

type Props = {
  params: Promise<{ area: string }>;
};

/**
 * エリアページは店舗ページと同じ静的生成方針（SEO Phase2 の store/[id]/page.tsx を参照）。
 * dynamicParams=false により、AREAS 掲載エリア以外へのアクセスは確実に real 404 になる
 * （fallback生成パスを通さずステータスがロックされる問題を避ける）。
 */
export const dynamicParams = false;

export function generateStaticParams(): { area: string }[] {
  return AREAS.map((a) => ({ area: a.id }));
}

/** 店舗ページと同じ更新頻度の考え方。エリアページ自体は静的文言中心のため長めでよいが、
 * 将来ライブ数値をクライアント側で足すことを見越して揃えておく。 */
export const revalidate = 120;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { area } = await params;
  const config = getAreaConfig(area);
  if (!config) notFound();

  const stores = getAreaStores(config);
  const base = getMetadataBaseUrl();
  const url = new URL(`/area/${encodeURIComponent(config.id)}`, base);

  const title = `${config.displayName}の相席ラウンジ 混雑状況・今夜の予測`;
  const description = `${config.displayName}エリアの相席ラウンジ${stores.length}店舗（${listBrandNames(stores)}）の混雑状況・今夜の予測をまとめて確認。実測データと機械学習の予測で、各店の今の混み具合や男女比を来店前にチェックできます。`;

  return {
    title,
    description,
    alternates: { canonical: url.href },
    openGraph: {
      title: `${title} | めぐりび`,
      description,
      url,
      type: "website",
      locale: "ja_JP",
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | めぐりび`,
      description,
    },
  };
}

/** エリア内に実在するブランド名を出現順・重複なしで「オリエンタルラウンジ・相席屋」のように並べる。 */
function listBrandNames(stores: StoreMeta[]): string {
  const seen: string[] = [];
  for (const s of stores) {
    const name = buildStoreBrandName(s);
    if (!seen.includes(name)) seen.push(name);
  }
  return seen.join("・");
}

/**
 * イントロ文。店舗数が1件のエリアでは「店舗ごとに傾向は異なる」という複数前提の一文を外す。
 * 単独店舗エリアは店名（＝ブランド名込み）を本文に明記し、地名だけの薄い文章にしない。
 */
function buildIntro(config: AreaConfig, stores: StoreMeta[]): string {
  if (stores.length > 1) {
    return `${config.displayName}にある相席ラウンジ${stores.length}店舗（${listBrandNames(stores)}）の、現在の混雑状況と今夜の混雑ピーク予測を、実測データと機械学習の予測でまとめています。行きたいお店の今の混み具合や男女比を、来店前にこのページでまとめて確認できます。店舗ごとに傾向は異なるため、気になるお店は個別ページで詳しいデータもあわせてご覧ください。`;
  }
  const only = stores[0];
  const name = only ? buildStoreFullName(only) : `${config.displayName}の相席ラウンジ`;
  // areaLabel が地名そのもの（例: 静岡）なら「静岡（静岡）」と冗長になるので付けない
  const place =
    only?.areaLabel && only.areaLabel !== config.displayName ? `（${only.areaLabel}）` : "";
  return `${config.displayName}の相席ラウンジ「${name}」${place}の、現在の混雑状況と今夜の混雑ピーク予測を、実測データと機械学習の予測でまとめています。今の混み具合や男女比を来店前に確認でき、個別ページでは時間帯別の混雑推移などさらに詳しいデータもあわせてご覧いただけます。`;
}

/**
 * 「相席屋 ○○」で検索して来た人向けの案内（発見最優先方針・2026-08-19）。
 * オリエンタルラウンジと相席屋は別ブランドで、この文言でも「同じ店」とは書かない。
 * ただし GSC 実測で「相席屋+地名」の検索が付いている地名に、当サイトが把握している相席ラウンジ
 * （オリエンタルラウンジ）しか無い場合、探している人にとって有用な選択肢なので正直に案内する。
 * 相席屋の店舗がそのエリアに存在するかどうかは当サイトの対象外で断定できないため
 * 「当サイトで扱っている○○の相席ラウンジは…」という言い方に留める。
 */
function buildAisekiyaSeekerNote(config: AreaConfig, stores: StoreMeta[]): string | null {
  const hasAisekiya = stores.some((s) => s.brand === "aisekiya");
  const orientals = stores.filter((s) => s.brand === "oriental");
  if (hasAisekiya || orientals.length === 0) return null;
  const names = orientals.map((s) => `「${buildStoreFullName(s)}」`).join("・");
  return `「相席屋 ${config.displayName}」で相席できるお店を探している方へ：当サイトで混雑状況を扱っている${config.displayName}の相席ラウンジは${names}です。相席屋とオリエンタルラウンジは別ブランドですが、どちらも男女が相席して出会える相席系ラウンジで、${config.displayName}で相席ラウンジをお探しならこちらの混雑状況が参考になります。`;
}

/**
 * エリア内の各店の実測（直近の人数/％・時間帯別・最終計測時刻）を /api/range_multi から取り、
 * 静的HTMLのテキストとして載せる。一覧ページと同じ limit（per-store キャッシュ共有）なので
 * バックエンドへの追加負荷はほぼ無い。失敗・タイムアウト・データ無しは null（セクションごと省く）。
 */
async function fetchAreaLive(stores: StoreMeta[]): Promise<AreaLiveSummary | null> {
  if (stores.length === 0) return null;
  const slugsCsv = stores.map((s) => s.slug).join(",");
  const json = await fetchBackendSnapshot<{
    ok?: boolean;
    by_slug?: Record<string, { rows?: unknown[] }>;
  }>(`/api/range_multi?stores=${encodeURIComponent(slugsCsv)}&limit=${STORE_CARD_RANGE_LIMIT}`, 60);
  if (!json?.ok || !json.by_slug) return null;
  const bySlug: Record<string, ReturnType<typeof parseRangeResponse>> = {};
  for (const store of stores) {
    const rows = json.by_slug[store.slug]?.rows;
    if (Array.isArray(rows)) bySlug[store.slug] = parseRangeResponse({ rows });
  }
  return buildAreaLiveSummary(stores, bySlug, new Date());
}

/** 店舗カード1件の補足テキスト。相席屋(ay_*)は人数を約束せず％表示のみの案内にする。 */
function buildStoreNote(store: StoreMeta): string {
  return isPercentCrowdBrand(store.brand)
    ? "混み具合（％）をリアルタイム表示"
    : "混雑人数・男女比をリアルタイム表示";
}

type AreaFaqItem = { question: string; answer: string };

/**
 * 2問目は店舗数で文言を分岐する: 複数店舗エリアは「選び方」、単独店舗エリアは
 * 「選ぶ」前提の質問が成立しない（比較対象が無い）ため「確認のしかた」に差し替える。
 */
function buildFaqItems(config: AreaConfig, storeCount: number): AreaFaqItem[] {
  const secondItem: AreaFaqItem =
    storeCount > 1
      ? {
          question: `${config.displayName}エリアの店舗はどう選べばいいですか？`,
          answer:
            "このページでは各店の現在の混雑状況を横並びで確認できます。気になる店舗のページに移動すると、男女比や混雑推移のグラフなど、より詳しいデータを見られます。",
        }
      : {
          question: `${config.displayName}の相席ラウンジの混雑状況はどこで確認できますか？`,
          answer:
            "このページ下部の店舗カードから店舗ページに移動すると、現在の人数・男女比や混雑推移のグラフなど、より詳しいデータを見られます。",
        };

  return [
    {
      question: `${config.displayName}の相席ラウンジは何時ごろ混みますか？`,
      answer:
        "混みやすい時間帯は店舗・曜日によって異なります。各店の店舗ページでは、実測データをもとにした今夜の時間帯別の混雑予測を公開しているので、来店前にそちらでご確認ください。",
    },
    secondItem,
    {
      question: "データはどのくらいの頻度で更新されますか？",
      answer:
        "各店舗ページの混雑状況・予測は営業時間中、数分単位で更新されます。あわせて日次・週次のレポートも公開しており、傾向を振り返る際の参考にできます。",
    },
  ];
}

export default async function AreaPage({ params }: Props) {
  const { area } = await params;
  const config = getAreaConfig(area);
  if (!config) notFound();

  const stores = getAreaStores(config);
  const base = getMetadataBaseUrl();
  const homeUrl = base.href.replace(/\/+$/, "") || base.href;
  const storesUrl = new URL("/stores", base).href;
  const areaUrl = new URL(`/area/${encodeURIComponent(config.id)}`, base).href;

  const breadcrumb = buildBreadcrumbList([
    { name: "ホーム", item: homeUrl },
    { name: "店舗一覧", item: storesUrl },
    { name: `${config.displayName}の相席ラウンジ`, item: areaUrl },
  ]);

  const intro = buildIntro(config, stores);
  const aisekiyaSeekerNote = buildAisekiyaSeekerNote(config, stores);
  const live = await fetchAreaLive(stores);
  const collectionDescription = `${config.displayName}エリアの相席ラウンジ${stores.length}店舗の混雑状況・今夜の予測をまとめたページ。`;

  const collectionPage = buildAreaCollectionPageJsonLd({
    name: `${config.displayName}の相席ラウンジ 混雑状況・今夜の予測`,
    description: collectionDescription,
    url: areaUrl,
    stores: stores.map((s) => ({
      name: buildStoreFullName(s),
      url: new URL(`/store/${encodeURIComponent(s.slug)}`, base).href,
    })),
  });

  const jsonLd = serializeJsonLd([breadcrumb, collectionPage]);
  const faqItems = buildFaqItems(config, stores.length);
  const otherAreas = AREAS.filter((a) => a.id !== config.id);

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd }} />

      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-6 text-slate-100">
        <nav aria-label="パンくずリスト" className="mb-3 text-xs text-slate-500">
          <Link href="/" className="hover:text-slate-300">
            ホーム
          </Link>
          <span className="mx-1.5">/</span>
          <Link href="/stores" className="hover:text-slate-300">
            店舗一覧
          </Link>
          <span className="mx-1.5">/</span>
          <span className="text-slate-400">{config.displayName}の相席ラウンジ</span>
        </nav>

        <h1 className="text-lg font-semibold text-slate-100 md:text-2xl">
          {config.displayName}の相席ラウンジ 混雑状況・今夜の予測
        </h1>

        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">{intro}</p>

        {/* 店舗一覧: 店名・エリア・リンクをSSRで載せる（curlで確認できるrawアンカー） */}
        <section aria-labelledby="area-store-list-heading" className="mt-8">
          <h2 id="area-store-list-heading" className="text-base font-semibold text-slate-100">
            {config.displayName}エリアの店舗一覧（{stores.length}店舗）
          </h2>
          <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {stores.map((store) => (
              <li key={store.slug}>
                <Link
                  href={`/store/${encodeURIComponent(store.slug)}`}
                  className="block rounded-xl border border-white/10 bg-white/[0.03] p-4 transition hover:border-indigo-400/30 hover:bg-white/[0.05]"
                >
                  <p className="text-sm font-semibold text-slate-100">
                    {buildStoreFullName(store)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{store.areaLabel}</p>
                  <p className="mt-2 text-xs text-indigo-300">
                    {buildStoreNote(store)} →
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {/* 各店の実測（SSRテキスト）: 取れた店だけ出す。0人・--:-- の空箱は作らない（areaLiveSummary.ts） */}
        {live && (
          <section aria-labelledby="area-live-heading" className="mt-10 max-w-3xl">
            <h2 id="area-live-heading" className="text-base font-semibold text-slate-100">
              {config.displayName}の各店の混雑（{live.nightLabel}の実測）
            </h2>
            <ul className="mt-4 space-y-4">
              {live.lines.map((line) => (
                <li key={line.slug} className="text-sm leading-relaxed text-slate-400">
                  <Link
                    href={`/store/${encodeURIComponent(line.slug)}`}
                    className="font-semibold text-slate-200 hover:text-indigo-200"
                  >
                    {line.storeName}
                  </Link>
                  {line.updatedText && (
                    <span className="ml-2 text-[11px] text-slate-500">{line.updatedText}</span>
                  )}
                  <p className="mt-1">
                    <span className="text-slate-300">{line.nowText}</span>
                  </p>
                  {line.hourlyText && (
                    <p className="mt-0.5 text-[12px]">
                      時間帯別の混雑（実測） <span className="text-slate-300">{line.hourlyText}</span>
                    </p>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] text-slate-500">
              数値は営業時間中に数分おきに更新されます。時刻はいずれも日本時間です。
            </p>
          </section>
        )}

        {/* 「相席屋 ○○」で探して来た人向けの正直な案内（同じ店だとは書かない・buildAisekiyaSeekerNote 参照） */}
        {aisekiyaSeekerNote && (
          <section aria-labelledby="area-seeker-heading" className="mt-10 max-w-3xl">
            <h2 id="area-seeker-heading" className="text-base font-semibold text-slate-100">
              {config.displayName}で相席屋・相席ラウンジをお探しの方へ
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-400">{aisekiyaSeekerNote}</p>
          </section>
        )}

        {/* エリア文脈: 一般的な内容のみ。特定店舗の評価・穴場断定・お告げ表現は書かない */}
        <section aria-labelledby="area-context-heading" className="mt-10 max-w-3xl">
          <h2 id="area-context-heading" className="text-base font-semibold text-slate-100">
            {config.displayName}で相席ラウンジを探すなら
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">
            {stores.length > 1
              ? `${config.displayName}エリアには複数の相席ラウンジ店舗があり、それぞれ独立して混雑状況が変動します。同じエリアでも店舗ごとに現在の人数・男女比・今夜の予測ピークは異なるため、このページでまとめて概況を確認したうえで、気になる店舗のページで詳しいデータを見るのがおすすめです。各店のデータは実測値とその推移から機械学習で予測した今夜のピークをあわせて掲載しています。`
              : `${config.displayName}エリアの相席ラウンジは、実測データと機械学習の予測をもとに現在の混雑状況と今夜のピークをまとめて確認できます。来店タイミングを決める前に、下の店舗ページで人数・男女比の推移もあわせてチェックするのがおすすめです。`}
          </p>
        </section>

        {/* FAQ: 視認可能なテキストのみ。FAQPage構造化データは意図的に付与しない（リッチリザルト廃止方針） */}
        <section aria-labelledby="area-faq-heading" className="mt-10 max-w-3xl">
          <h2 id="area-faq-heading" className="text-base font-semibold text-slate-100">
            よくある質問
          </h2>
          <dl className="mt-4 space-y-5">
            {faqItems.map((item) => (
              <div key={item.question}>
                <dt className="text-sm font-semibold text-slate-200">{item.question}</dt>
                <dd className="mt-1.5 text-sm leading-relaxed text-slate-400">{item.answer}</dd>
              </div>
            ))}
          </dl>
        </section>

        {/* 内部リンク: 店舗一覧・他エリアへの相互リンク */}
        <section aria-labelledby="area-links-heading" className="mt-10 border-t border-white/10 pt-6">
          <h2 id="area-links-heading" className="text-sm font-semibold text-slate-100">
            他のエリア・店舗一覧
          </h2>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs">
            <li>
              <Link href="/stores" className="text-indigo-300 hover:text-indigo-200">
                全店舗一覧 →
              </Link>
            </li>
            {otherAreas.map((a) => (
              <li key={a.id}>
                <Link
                  href={`/area/${encodeURIComponent(a.id)}`}
                  className="text-slate-300 hover:text-slate-100"
                >
                  {a.displayName}の相席ラウンジ一覧 →
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
