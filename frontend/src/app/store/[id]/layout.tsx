import type { Metadata } from "next";
import { getStoreMetaBySlug, buildStoreFullName } from "@/app/config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const base = getMetadataBaseUrl();

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const meta = getStoreMetaBySlug(id);
  // 店舗のブランド（オリエンタルラウンジ / 相席屋 / JIS）を正しく反映。以前は全店
  // "Oriental Lounge" 固定で、相席屋の店まで誤表記＝「相席屋 ◯◯」等の検索で不利だった。
  const fullName = buildStoreFullName(meta);
  const title = `${fullName}の混雑・リアルタイム人数`;
  const description = `${fullName}（${meta.areaLabel}・${meta.regionLabel}）の今の人数・男女比・混雑予測をリアルタイムで。今夜の狙い目の時間帯をデータでご案内。`;
  const path = `/store/${meta.slug}`;

  return {
    title,
    description,
    openGraph: {
      title: `${title} | めぐりび`,
      description,
      url: new URL(path, base),
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | めぐりび`,
      description,
    },
  };
}

export default function StoreSlugLayout({ children }: { children: React.ReactNode }) {
  return children;
}
