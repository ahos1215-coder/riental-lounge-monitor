"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { StoreCard } from "@/components/StoreCard";
import MeguribiDashboardPreview from "../../../components/MeguribiDashboardPreview";
import {
  isFavoriteStore,
  recordStoreVisit,
  toggleFavoriteStore,
} from "@/lib/browser/meguribiStorage";
import { DEFAULT_STORE, STORES, getStoreMetaBySlug } from "../../config/stores";

function StorePageFallback() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8">
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded bg-slate-700/80" />
        <div className="h-72 w-full animate-pulse rounded-2xl bg-slate-800/80" />
      </div>
      <div className="space-y-3">
        <div className="h-4 w-40 animate-pulse rounded bg-slate-700/80" />
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-44 animate-pulse rounded-2xl border border-slate-800/80 bg-slate-900/60"
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function StorePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams();

  const slugRaw = (params as { id?: string | string[] }).id;
  const slugFromPath =
    typeof slugRaw === "string"
      ? slugRaw
      : Array.isArray(slugRaw)
      ? slugRaw[0]
      : "";

  const meta = getStoreMetaBySlug(slugFromPath || searchParams.get("store") || DEFAULT_STORE);
  const slug = meta.slug;

  useEffect(() => {
    if (!slug) return;

    const current = searchParams.get("store");
    if (current === slug) return;

    const sp = new URLSearchParams(searchParams.toString());
    sp.set("store", slug);
    const qs = sp.toString();

    router.replace(qs ? `/store/${slug}?${qs}` : `/store/${slug}`, {
      scroll: false,
    });
  }, [router, searchParams, slug]);

  useEffect(() => {
    if (!slug) return;
    recordStoreVisit(slug);
  }, [slug]);

  const digestStores = useMemo(
    () => STORES.filter((s) => s.slug !== slug).slice(0, 4),
    [slug],
  );

  const [favorite, setFavorite] = useState(false);
  useEffect(() => {
    setFavorite(isFavoriteStore(slug));
  }, [slug]);

  return (
    <div className="space-y-8">
      <div className="mx-auto flex w-full max-w-6xl justify-end px-4 pt-2">
        <button
          type="button"
          onClick={() => {
            const next = toggleFavoriteStore(slug);
            setFavorite(next);
          }}
          className="rounded-full border border-amber-400/35 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-100 transition hover:border-amber-300/60 hover:bg-amber-500/20"
          aria-pressed={favorite}
        >
          {favorite ? "★ お気に入り済み" : "☆ お気に入りに追加"}
        </button>
      </div>

      <MeguribiDashboardPreview />

      <section className="mx-auto w-full max-w-6xl space-y-3 px-4">
        <h2 className="text-sm font-semibold text-slate-100">Check other stores</h2>
        <div className="grid gap-3 md:grid-cols-4">
          {digestStores.map((store, idx) => (
            <StoreCard
              key={store.slug}
              slug={store.slug}
              label={`Oriental Lounge ${store.label}`}
              brandLabel="ORIENTAL LOUNGE"
              areaLabel={store.areaLabel}
              isHighlight={idx === 0}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

export default function StorePage() {
  return (
    <Suspense fallback={<StorePageFallback />}>
      <StorePageInner />
    </Suspense>
  );
}
