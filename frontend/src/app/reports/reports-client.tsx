"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  STORES,
  STORE_REGION_FILTER_ORDER,
  STORE_REGION_BUTTON_LABEL,
  getStoreMetaBySlugStrict,
  type StoreMeta,
} from "@/app/config/stores";

type ReportTab = "daily" | "weekly";

type ReportItem = {
  store_slug: string;
  target_date: string;
  edition?: string;
  created_at?: string;
  heading: string | null;
};

type ReportItemWithMeta = ReportItem & { meta: StoreMeta };

const EDITION_LABELS: Record<string, string> = {
  evening_preview: "18:00 便",
  late_update: "21:30 便",
};

function formatJst(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function CardSkeleton() {
  return (
    <div className="h-32 animate-pulse rounded-2xl border border-slate-800 bg-slate-900/40" />
  );
}

export function ReportsPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const tabFromUrl = searchParams.get("tab") === "weekly" ? "weekly" : "daily";
  const regionFromUrl = searchParams.get("region") ?? "all";
  const queryFromUrl = searchParams.get("q") ?? "";

  const [tab, setTab] = useState<ReportTab>(tabFromUrl);
  const [region, setRegion] = useState(regionFromUrl);
  const [query, setQuery] = useState(queryFromUrl);
  const [dailyItems, setDailyItems] = useState<ReportItemWithMeta[]>([]);
  const [weeklyItems, setWeeklyItems] = useState<ReportItemWithMeta[]>([]);
  const [loading, setLoading] = useState(true);

  const updateUrl = useCallback(
    (newTab: ReportTab, newRegion: string, newQuery: string) => {
      const params = new URLSearchParams();
      if (newTab !== "daily") params.set("tab", newTab);
      if (newRegion !== "all") params.set("region", newRegion);
      if (newQuery.trim()) params.set("q", newQuery.trim());
      const qs = params.toString();
      router.replace(qs ? `/reports?${qs}` : "/reports", { scroll: false });
    },
    [router],
  );

  const handleTabChange = useCallback(
    (t: ReportTab) => {
      setTab(t);
      updateUrl(t, region, query);
    },
    [region, query, updateUrl],
  );

  const handleRegionChange = useCallback(
    (r: string) => {
      setRegion(r);
      updateUrl(tab, r, query);
    },
    [tab, query, updateUrl],
  );

  const handleQueryChange = useCallback(
    (q: string) => {
      setQuery(q);
      updateUrl(tab, region, q);
    },
    [tab, region, updateUrl],
  );

  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      setLoading(true);
      try {
        const [dailyRes, weeklyRes] = await Promise.all([
          fetch("/api/reports/list?type=daily", { signal: ac.signal }),
          fetch("/api/reports/list?type=weekly", { signal: ac.signal }),
        ]);

        const parse = async (res: Response): Promise<ReportItemWithMeta[]> => {
          if (!res.ok) return [];
          const json = (await res.json()) as { ok: boolean; data?: ReportItem[] };
          if (!json.ok || !Array.isArray(json.data)) return [];
          return json.data
            .map((r) => {
              const meta = getStoreMetaBySlugStrict(r.store_slug);
              if (!meta) return null;
              return { ...r, meta };
            })
            .filter(Boolean) as ReportItemWithMeta[];
        };

        if (!ac.signal.aborted) {
          setDailyItems(await parse(dailyRes));
          setWeeklyItems(await parse(weeklyRes));
        }
      } catch {
        /* ignore */
      } finally {
        if (!ac.signal.aborted) setLoading(false);
      }
    })();
    return () => ac.abort();
  }, []);

  const items = tab === "daily" ? dailyItems : weeklyItems;

  const filtered = useMemo(() => {
    let result = items;
    if (region !== "all") {
      result = result.filter((r) => r.meta.regionLabel === region);
    }
    const q = query.trim().toLowerCase();
    if (q) {
      result = result.filter(
        (r) =>
          r.meta.label.toLowerCase().includes(q) ||
          r.meta.areaLabel.toLowerCase().includes(q) ||
          r.meta.slug.includes(q),
      );
    }
    return result;
  }, [items, region, query]);

  const storesWithoutReport = useMemo(() => {
    let base = STORES as readonly StoreMeta[];
    if (region !== "all") {
      base = base.filter((s) => s.regionLabel === region);
    }
    const q = query.trim().toLowerCase();
    if (q) {
      base = base.filter(
        (s) =>
          s.label.toLowerCase().includes(q) ||
          s.areaLabel.toLowerCase().includes(q) ||
          s.slug.includes(q),
      );
    }
    const slugSet = new Set(items.map((i) => i.store_slug));
    return base.filter((s) => !slugSet.has(s.slug));
  }, [items, region, query]);

  const regionCounts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const item of items) {
      const r = item.meta.regionLabel;
      map[r] = (map[r] ?? 0) + 1;
    }
    return map;
  }, [items]);

  const borderHover =
    tab === "daily" ? "hover:border-indigo-500/50" : "hover:border-amber-500/50";
  const badgeBg =
    tab === "daily" ? "bg-indigo-500/20 text-indigo-200" : "bg-amber-500/20 text-amber-200";
  const hoverText =
    tab === "daily" ? "group-hover:text-indigo-200" : "group-hover:text-amber-200";

  return (
    <div className="relative min-h-screen bg-black font-display text-slate-50">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(79,70,229,0.10)_0%,transparent_30%)]" />
      <div className="relative z-10">
        <main className="mx-auto max-w-5xl px-4 py-8">
          <div className="mb-2">
            <Link
              href="/"
              className="text-xs text-white/50 transition hover:text-white"
            >
              ← トップへ
            </Link>
          </div>

          <header className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight md:text-3xl">
              AI予測レポート
            </h1>
            <p className="mt-2 text-sm text-white/60">
              機械学習モデルの予測と実測データをもとに、AIが各店舗の混雑傾向を自動分析したレポートです。
            </p>
          </header>

          {/* Tab + Search */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-1">
              <button
                type="button"
                onClick={() => handleTabChange("daily")}
                className={`rounded-md px-4 py-1.5 text-xs font-bold transition ${
                  tab === "daily"
                    ? "bg-indigo-500/20 text-indigo-200"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Daily Report
                {dailyItems.length > 0 && (
                  <span className="ml-1.5 text-[10px] font-normal text-white/40">
                    {dailyItems.length}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => handleTabChange("weekly")}
                className={`rounded-md px-4 py-1.5 text-xs font-bold transition ${
                  tab === "weekly"
                    ? "bg-amber-500/20 text-amber-200"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Weekly Report
                {weeklyItems.length > 0 && (
                  <span className="ml-1.5 text-[10px] font-normal text-white/40">
                    {weeklyItems.length}
                  </span>
                )}
              </button>
            </div>

            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                placeholder="店舗名・エリアで検索…"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-3 text-xs text-white placeholder-slate-500 outline-none focus:border-slate-500 sm:w-56"
              />
              <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-500">
                🔍
              </span>
            </div>
          </div>

          {/* Region filter */}
          <div className="mb-5 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => handleRegionChange("all")}
              className={`rounded-full border px-3 py-1 text-[11px] font-semibold transition ${
                region === "all"
                  ? "border-white/30 bg-white/10 text-white"
                  : "border-white/10 bg-white/5 text-white/50 hover:text-white/70"
              }`}
            >
              すべて
              <span className="ml-1 text-[10px] font-normal text-white/40">
                {items.length}
              </span>
            </button>
            {STORE_REGION_FILTER_ORDER.map((r) => {
              const count = regionCounts[r] ?? 0;
              const label = STORE_REGION_BUTTON_LABEL[r] ?? r;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => handleRegionChange(r)}
                  className={`rounded-full border px-3 py-1 text-[11px] font-semibold transition ${
                    region === r
                      ? "border-white/30 bg-white/10 text-white"
                      : "border-white/10 bg-white/5 text-white/50 hover:text-white/70"
                  }`}
                >
                  {label}
                  {count > 0 && (
                    <span className="ml-1 text-[10px] font-normal text-white/40">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Report description */}
          <div className="mb-5 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3">
            {tab === "daily" ? (
              <p className="text-xs leading-relaxed text-white/55">
                <strong className="text-indigo-200">Daily Report</strong> — 毎日
                18:00（夕方プレビュー）と 21:30（最新更新）に自動生成。今夜の混雑傾向・おすすめの時間帯をAIが分析します。
              </p>
            ) : (
              <p className="text-xs leading-relaxed text-white/55">
                <strong className="text-amber-200">Weekly Report</strong> — 毎週水曜に自動生成。
                1週間分の来客データ・曜日ごとの傾向・前週比をAIが分析してまとめます。
              </p>
            )}
          </div>

          {/* Loading */}
          {loading && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[...Array(6)].map((_, i) => (
                <CardSkeleton key={i} />
              ))}
            </div>
          )}

          {/* Empty */}
          {!loading && filtered.length === 0 && (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-6 text-center">
              {query || region !== "all" ? (
                <p className="text-sm text-slate-400">
                  条件に一致するレポートが見つかりません。フィルタや検索条件を変更してください。
                </p>
              ) : (
                <p className="text-sm text-slate-400">
                  {tab === "daily"
                    ? "現在、公開済みの Daily Report はありません。18:00 / 21:30 の自動生成後に表示されます。"
                    : "現在、公開済みの Weekly Report はありません。水曜日の自動生成後に表示されます。"}
                </p>
              )}
            </div>
          )}

          {/* Cards */}
          {!loading && filtered.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((item) => (
                <Link
                  key={item.store_slug}
                  href={`/reports/${tab}/${encodeURIComponent(item.store_slug)}`}
                  className={`group flex flex-col rounded-2xl border border-slate-800 bg-slate-950/80 p-4 transition hover:bg-slate-900/80 ${borderHover}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-sm font-bold text-white ${hoverText}`}>
                      {item.meta.label}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold ${badgeBg}`}
                    >
                      {tab === "daily" ? "Daily" : "Weekly"}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-white/40">
                    {item.meta.areaLabel}
                    <span className="ml-2 text-white/25">{item.meta.regionLabel}</span>
                  </p>
                  {item.heading && (
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-white/70">
                      {item.heading}
                    </p>
                  )}
                  <div className="mt-auto flex items-center justify-between gap-2 pt-3">
                    <span className="text-[10px] text-white/35">
                      {item.target_date}
                      {tab === "daily" &&
                        item.edition &&
                        ` · ${EDITION_LABELS[item.edition] ?? item.edition}`}
                    </span>
                    <span className="text-[10px] text-white/35">
                      {formatJst(item.created_at)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}

          {/* Stores without report */}
          {!loading && storesWithoutReport.length > 0 && filtered.length > 0 && (
            <section className="mt-8">
              <h2 className="mb-3 text-sm font-semibold text-white/60">
                レポート未生成の店舗
              </h2>
              <div className="flex flex-wrap gap-2">
                {storesWithoutReport.map((s) => (
                  <Link
                    key={s.slug}
                    href={`/store/${s.slug}?store=${s.slug}`}
                    className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-white/50 transition hover:border-white/25 hover:text-white/70"
                  >
                    {s.label}
                    <span className="ml-1 text-[9px] text-white/25">{s.areaLabel}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* Footer info */}
          <section className="mt-10 rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
            <h2 className="text-sm font-semibold text-white/80">AI予測レポートとは</h2>
            <p className="mt-2 text-xs leading-relaxed text-white/55">
              機械学習モデル（train ML model）の予測と、5分おきの実測データを組み合わせて、
              AIが各店舗の混雑傾向・おすすめの時間帯・男女比の変化を自動分析するレポートです。
              Daily Report は毎日 18:00 と 21:30 に、Weekly Report は毎週水曜に自動生成されます。
            </p>
            <div className="mt-3 flex gap-3">
              <Link
                href="/blog"
                className="text-xs font-medium text-indigo-300 hover:text-indigo-200"
              >
                編集ブログ記事 →
              </Link>
              <Link
                href="/stores"
                className="text-xs font-medium text-indigo-300 hover:text-indigo-200"
              >
                店舗一覧 →
              </Link>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
