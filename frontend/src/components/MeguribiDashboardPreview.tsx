"use client";

import { useRouter, useSearchParams } from "next/navigation";
import PreviewMainSection from "./PreviewMainSection";
import { useStorePreviewData } from "../app/hooks/useStorePreviewData";
import {
  DEFAULT_STORE,
  getStoreMetaBySlug,
} from "../app/config/stores";

export default function MeguribiDashboardPreview() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const slug = searchParams.get("store") ?? DEFAULT_STORE;
  const meta = getStoreMetaBySlug(slug);

  const { snapshot, loading, error } = useStorePreviewData(meta.slug);

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
      />
    </main>
  );
}
