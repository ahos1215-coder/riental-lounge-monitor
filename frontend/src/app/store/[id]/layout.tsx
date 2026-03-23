import type { Metadata } from "next";
import { getStoreMetaBySlug } from "@/app/config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const base = getMetadataBaseUrl();

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const meta = getStoreMetaBySlug(id);
  const title = `Oriental Lounge ${meta.label}`;
  const description = `${meta.areaLabel}（${meta.regionLabel}）の混雑傾向・男女比・予測ダッシュボード。`;
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
