import type { Metadata } from "next";
import Link from "next/link";

import {
  BLOG_CATEGORIES,
  formatYmdToSlash,
  getAllPostMetas,
  isCategoryId,
  type BlogCategoryId,
} from "@/lib/blog/content";
import { getMetadataBaseUrl } from "@/lib/siteUrl";
import { STORES } from "../config/stores";

const blogBase = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "ブログ",
  description:
    "相席系ラウンジ・バーの攻略や夜の楽しみ方、混雑傾向の読み方をわかりやすく解説します。",
  openGraph: {
    title: "ブログ | めぐりび",
    description:
      "相席系ラウンジ・バーの攻略や夜の楽しみ方、混雑傾向の読み方をわかりやすく解説します。",
    url: new URL("/blog", blogBase),
    type: "website",
    locale: "ja_JP",
  },
  twitter: {
    card: "summary_large_image",
    title: "ブログ | めぐりび",
    description:
      "相席系ラウンジ・バーの攻略や夜の楽しみ方、混雑傾向の読み方をわかりやすく解説します。",
  },
};

type SearchParams = Record<string, string | string[] | undefined>;

function normalizeParam(v: string | string[] | undefined): string | undefined {
  if (!v) return undefined;
  return Array.isArray(v) ? v[0] : v;
}

function toInt(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

type BlogCategoryRow = (typeof BLOG_CATEGORIES)[number];

function isBlogCategoryLink(
  c: BlogCategoryRow,
): c is BlogCategoryRow & { id: BlogCategoryId } {
  return c.id !== "all";
}

function buildHref(params: { cat?: "all" | BlogCategoryId; sort?: "all" | "popular" | "latest"; q?: string; page?: number }): string {
  const p = new URLSearchParams();
  if (params.cat && params.cat !== "all") p.set("cat", params.cat);
  if (params.sort && params.sort !== "all") p.set("sort", params.sort);
  if (params.q) p.set("q", params.q);
  if (params.page && params.page > 1) p.set("page", String(params.page));
  const qs = p.toString();
  return qs ? `/blog?${qs}` : "/blog";
}

export default async function BlogPage({ searchParams }: { searchParams?: Promise<SearchParams> }) {
  const sp = searchParams ? await searchParams : undefined;

  const rawCat = normalizeParam(sp?.cat) ?? "all";
  const rawSort = normalizeParam(sp?.sort) ?? "all";
  const q = (normalizeParam(sp?.q) ?? "").trim().slice(0, 60);
  const page = toInt(normalizeParam(sp?.page), 1);

  const cat: "all" | BlogCategoryId = rawCat === "all" ? "all" : isCategoryId(rawCat) ? rawCat : "all";
  const sort: "all" | "popular" | "latest" = rawSort === "popular" || rawSort === "latest" ? rawSort : "all";

  let list = getAllPostMetas();

  if (cat !== "all") list = list.filter((p) => p.categoryId === cat);
  if (q) {
    const qq = q.toLowerCase();
    list = list.filter(
      (p) => p.title.toLowerCase().includes(qq) || p.description.toLowerCase().includes(qq),
    );
  }

  if (sort === "popular") list.sort((a, b) => b.views - a.views);
  if (sort === "latest") list.sort((a, b) => (a.date < b.date ? 1 : -1));

  const pageSize = 9;
  const totalPages = Math.max(1, Math.ceil(list.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const start = (currentPage - 1) * pageSize;
  const rows = list.slice(start, start + pageSize);

  const popular = getAllPostMetas()
    .slice()
    .sort((a, b) => b.views - a.views)
    .slice(0, 5);

  const dailyReportStores = STORES.slice(0, 6);

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/4 top-[-120px] h-[520px] w-[520px] rounded-full bg-indigo-600/10 blur-3xl" />
        <div className="absolute right-1/4 top-[80px] h-[520px] w-[520px] rounded-full bg-amber-400/10 blur-3xl" />
      </div>

      <div className="relative mx-auto w-full max-w-6xl px-4 pb-16 pt-10">
        <h1 className="text-3xl font-black tracking-tight">ブログ</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/60">
          相席系ラウンジ・バーの立ち回りや夜の楽しみ方、混雑の読み方などをわかりやすくまとめています。店舗別の自動更新記事もここから辿れます。
        </p>

        <form className="mt-6 flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <input
            name="q"
            defaultValue={q}
            placeholder="記事を検索（例：初心者、予測、会話）"
            className="h-11 min-w-0 flex-1 rounded-xl border border-white/10 bg-white/5 px-4 text-sm text-white placeholder:text-white/30 outline-none focus:border-white/20"
          />
          {cat !== "all" && <input type="hidden" name="cat" value={cat} />}
          {sort !== "all" && <input type="hidden" name="sort" value={sort} />}
          <button
            type="submit"
            className="h-11 w-full shrink-0 rounded-xl border border-white/10 bg-white/5 px-4 text-sm font-semibold hover:border-white/20 sm:w-auto"
          >
            検索
          </button>
        </form>

        <div className="mt-4 flex flex-wrap gap-2">
          {BLOG_CATEGORIES.filter(isBlogCategoryLink).map((c) => (
            <Link
              key={c.id}
              href={buildHref({ cat: c.id, sort, q, page: 1 })}
              className={
                "rounded-full border px-3 py-1 text-xs font-semibold " +
                (cat === c.id ? "border-white/25 bg-white/10" : "border-white/10 bg-white/5 hover:border-white/20")
              }
            >
              {c.label}
            </Link>
          ))}
          <Link
            href={buildHref({ cat: "all", sort, q, page: 1 })}
            className={
              "rounded-full border px-3 py-1 text-xs font-semibold " +
              (cat === "all" ? "border-white/25 bg-white/10" : "border-white/10 bg-white/5 hover:border-white/20")
            }
          >
            すべて
          </Link>
        </div>

        <div className="mt-6 flex items-center gap-4 border-b border-white/10">
          {(["all", "popular", "latest"] as const).map((k) => (
            <Link
              key={k}
              href={buildHref({ cat, sort: k, q, page: 1 })}
              className={
                "pb-3 text-sm font-semibold " +
                (sort === k ? "border-b-2 border-white text-white" : "text-white/60 hover:text-white")
              }
            >
              {k === "all" ? "ALL" : k === "popular" ? "人気順" : "新着順"}
            </Link>
          ))}
        </div>

        <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="sm:col-span-2 lg:col-span-3 rounded-2xl border border-indigo-500/25 bg-indigo-500/5 p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-bold text-indigo-200">AI予測・Daily Report</h2>
                <Link
                  href="/reports"
                  className="text-[11px] text-indigo-300/80 hover:text-indigo-200"
                >
                  AI予測レポート一覧 →
                </Link>
              </div>
              <p className="mt-2 text-xs text-white/60">
                毎日 18:00 / 21:30 に自動生成される最新予測予報。店舗ページから各店の最新レポートを確認できます。
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {dailyReportStores.map((s) => (
                  <Link
                    key={s.slug}
                    href={`/reports/daily/${encodeURIComponent(s.slug)}`}
                    className="rounded-full border border-indigo-400/40 bg-indigo-500/10 px-3 py-1 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/20"
                  >
                    {s.label}
                  </Link>
                ))}
                <Link
                  href="/stores"
                  className="rounded-full border border-white/20 bg-white/5 px-3 py-1 text-xs font-semibold text-white/70 hover:bg-white/10"
                >
                  全店舗 →
                </Link>
              </div>
            </div>
            {rows.map((post) => (
              <Link
                key={post.slug}
                href={`/blog/${post.slug}`}
                className="group overflow-hidden rounded-2xl border border-white/10 bg-white/5 hover:border-white/20"
              >
                <div className="relative aspect-[16/9]">
                  <div className={"absolute inset-0 " + post.heroClassName} />
                  <div className="absolute inset-0 bg-black/40" />
                </div>

                <div className="p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span
                      className={
                        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold text-white " +
                        post.badgeClassName
                      }
                    >
                      {post.categoryLabel}
                    </span>
                    <span className="text-xs text-white/40">
                      {formatYmdToSlash(post.date)} ・ {post.minutes}分
                    </span>
                  </div>

                  <p className="mt-3 text-sm font-black leading-snug text-white group-hover:text-white/90">
                    {post.title}
                  </p>
                  <p className="mt-2 text-xs text-white/60 [display:-webkit-box] [-webkit-line-clamp:2] [-webkit-box-orient:vertical] overflow-hidden">
                    {post.description}
                  </p>
                </div>
              </Link>
            ))}
          </section>

          <aside className="space-y-4">
            <div className="rounded-2xl border border-indigo-500/25 bg-indigo-500/5 p-5">
              <h2 className="text-sm font-bold text-indigo-100">AI予測レポート</h2>
              <p className="mt-2 text-xs text-white/60 leading-relaxed">
                Daily / Weekly の自動生成レポートは専用ページで公開しています。
              </p>
              <div className="mt-3 space-y-2">
                <Link
                  href="/reports"
                  className="block rounded-lg border border-indigo-400/25 bg-black/20 px-3 py-2 text-xs text-indigo-100 hover:bg-indigo-500/10"
                >
                  AI予測レポート一覧（Daily / Weekly）
                </Link>
                <Link
                  href="/stores"
                  className="block rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white/70 hover:bg-white/5"
                >
                  全店舗を見る →
                </Link>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
              <h2 className="text-sm font-bold">人気記事ランキング</h2>
              <div className="mt-4 space-y-3">
                {popular.map((p, idx) => (
                  <Link key={p.slug} href={`/blog/${p.slug}`} className="block hover:opacity-90">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 text-lg font-black text-amber-300">{idx + 1}</div>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-white">{p.title}</p>
                        <p className="mt-1 text-[11px] text-white/50">
                          {formatYmdToSlash(p.date)} ・ {p.categoryLabel}
                        </p>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>

              <div className="mt-4 rounded-xl border border-white/10 bg-black/30 p-3 text-xs leading-relaxed text-white/60">
                ※ 閲覧数ランキングはコンテンツ内の値に基づくデモ表示です。AI予測レポートは上部または左サイドバーからご確認ください。
              </div>
            </div>
          </aside>
        </div>

        {totalPages > 1 && (
          <div className="mt-10 flex items-center justify-center gap-2">
            <Link
              href={buildHref({ cat, sort, q, page: Math.max(1, currentPage - 1) })}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:border-white/20"
            >
              前へ
            </Link>
            <span className="text-xs text-white/60">
              {currentPage} / {totalPages}
            </span>
            <Link
              href={buildHref({ cat, sort, q, page: Math.min(totalPages, currentPage + 1) })}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs hover:border-white/20"
            >
              次へ
            </Link>
          </div>
        )}
      </div>
    </main>
  );
}