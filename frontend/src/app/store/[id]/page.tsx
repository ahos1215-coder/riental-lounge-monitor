import type { Metadata } from "next";
import { buildStoreFullName, getStoreMetaBySlugStrict } from "../../config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { serializeJsonLd } from "@/lib/jsonLd";
import StorePageClient from "./StorePageClient";

type Props = {
  params: Promise<{ id: string }>;
};

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

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      )}
      <StorePageClient />
    </>
  );
}
