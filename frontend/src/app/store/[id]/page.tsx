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

type ForecastPoint = { ts: string; total_pred?: number };

function ForecastQuickPanel({ slug }: { slug: string }) {
  const [state, setState] = useState<{
    loading: boolean;
    peak: string;
    calm: string;
    maxPred: number;
  }>({ loading: true, peak: "--:--", calm: "--:--", maxPred: 0 });

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await fetch(`/api/forecast_today?store=${encodeURIComponent(slug)}`, {
          cache: "no-store",
        });
        const data = (await res.json()) as { data?: ForecastPoint[] };
        const rows = Array.isArray(data?.data) ? data.data : [];
        if (!rows.length) {
          if (mounted) setState({ loading: false, peak: "--:--", calm: "--:--", maxPred: 0 });
          return;
        }
        let peak = rows[0];
        let calm = rows[0];
        for (const r of rows) {
          const v = Number(r.total_pred ?? 0);
          if (v > Number(peak.total_pred ?? 0)) peak = r;
          if (v < Number(calm.total_pred ?? 0)) calm = r;
        }
        const fmt = (iso: string) =>
          new Intl.DateTimeFormat("ja-JP", {
            timeZone: "Asia/Tokyo",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }).format(new Date(iso));
        if (mounted) {
          setState({
            loading: false,
            peak: fmt(peak.ts),
            calm: fmt(calm.ts),
            maxPred: Math.round(Number(peak.total_pred ?? 0)),
          });
        }
      } catch {
        if (mounted) setState({ loading: false, peak: "--:--", calm: "--:--", maxPred: 0 });
      }
    })();
    return () => {
      mounted = false;
    };
  }, [slug]);

  return (
    <section className="mx-auto w-full max-w-6xl px-4">
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
        <p className="text-[11px] font-semibold text-emerald-200">ML 2.0 今日の予測ハイライト</p>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          <div className="rounded-xl border border-white/10 bg-black/20 p-2.5">
            <p className="text-[10px] text-white/60">賑わいピークの目安</p>
            <p className="mt-1 text-xl font-bold leading-none text-white">{state.loading ? "..." : state.peak}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 p-2.5">
            <p className="text-[10px] text-white/60">落ち着いて過ごしやすい目安</p>
            <p className="mt-1 text-xl font-bold leading-none text-white">{state.loading ? "..." : state.calm}</p>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/20 p-2.5">
            <p className="text-[10px] text-white/60">予測最大人数（参考）</p>
            <p className="mt-1 text-xl font-bold leading-none text-white">{state.loading ? "..." : `${Math.round(state.maxPred)}人`}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

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
      <ForecastQuickPanel slug={slug} />

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
