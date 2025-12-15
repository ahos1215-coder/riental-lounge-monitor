"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { StoreCard } from "@/components/StoreCard";
import MeguribiDashboardPreview from "../../../components/MeguribiDashboardPreview";
import { DEFAULT_STORE, STORES, getStoreMetaBySlug } from "../../config/stores";

const LAST_STORE_KEY = "meguribi:lastStoreSlug";

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
    try {
      window.localStorage.setItem(LAST_STORE_KEY, slug);
    } catch {
      // ignore
    }
  }, [slug]);

  const digestStores = useMemo(() => STORES.slice(0, 4), []);

  return (
    <div className="space-y-8">
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
              stats={{
                genderRatio: "pending",
                crowdLevel: "pending",
                recommendLabel: "pending",
              }}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

export default function StorePage() {
  return (
    <Suspense fallback={null}>
      <StorePageInner />
    </Suspense>
  );
}
