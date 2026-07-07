"use client";

import type { ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

const PreviewMainSection = dynamic(() => import("./PreviewMainSection"), {
  ssr: false,
  loading: () => (
    <div className="h-80 w-full animate-pulse rounded-2xl bg-slate-800/60" />
  ),
});
import { useStorePreviewData, type StoreSnapshot } from "../app/hooks/useStorePreviewData";
import {
  DEFAULT_STORE,
  getStoreMetaBySlug,
} from "../app/config/stores";

type MeguribiDashboardPreviewProps = {
  /** 店舗名横にお気に入りボタンなど */
  headerActions?: ReactNode;
  /** サーバーで取得済みの初回スナップショット（page.tsx 由来）。無ければ通常の CSR。 */
  initialSnapshot?: StoreSnapshot | null;
  /**
   * URLパス（/store/[id]）由来の店舗 slug。渡された場合、?store= クエリより優先する。
   *
   * 経緯: このコンポーネント単体では従来 `searchParams.get("store") ?? DEFAULT_STORE` だけで
   * slug を決めていたが、/store/[id] への直接アクセス直後は StorePageInner の URL 同期
   * useEffect がまだ走っておらず `?store=` が付いていない瞬間があり、その一瞬だけ
   * DEFAULT_STORE 相当にフォールバックしてしまっていた（元コードでは毎回 loading:true から
   * 始まるため無害だったが、initialSnapshot による即時描画は「最初のレンダーで正しい店舗の
   * slug と一致するか」に依存するため、この一瞬のズレが致命的になる）。
   * StorePageInner 自身は既に slugFromPath を searchParams より優先しているため、同じ
   * 優先順位をここでも揃える。
   */
  pathSlug?: string;
};

export default function MeguribiDashboardPreview({ headerActions, initialSnapshot, pathSlug }: MeguribiDashboardPreviewProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const slug = pathSlug || searchParams.get("store") || DEFAULT_STORE;
  const meta = getStoreMetaBySlug(slug);

  const {
    snapshot,
    loading,
    error,
    rangeMode,
    setRangeMode,
    customDate,
    setCustomDate,
    selectedBaseDate,
  } = useStorePreviewData(meta.slug, initialSnapshot);

  const handleSelectStore = (nextSlug: string) => {
    if (!nextSlug || nextSlug === meta.slug) return;

    const params = new URLSearchParams(searchParams.toString());
    params.set("store", nextSlug);
    const query = params.toString();

    router.push(
      query ? `/store/${nextSlug}?${query}` : `/store/${nextSlug}`,
      { scroll: false },
    );
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 text-slate-50">
      <PreviewMainSection
        storeSlug={meta.slug}
        snapshot={snapshot}
        onSelectStore={handleSelectStore}
        loading={loading}
        error={error}
        rangeMode={rangeMode}
        onChangeRangeMode={setRangeMode}
        customDate={customDate}
        onChangeCustomDate={setCustomDate}
        selectedBaseDate={selectedBaseDate}
        storeHeaderActions={headerActions}
      />
    </main>
  );
}
