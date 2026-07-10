"use client";

import Link from "next/link";
import { ChevronRight, BookOpen } from "lucide-react";
import { FadeIn } from "@/components/ui/FadeIn";
import type { HomeBlogTeaser } from "./homeTypes";

export function HomeBlogStrip({
  latestBlogPosts,
}: {
  latestBlogPosts: HomeBlogTeaser[];
}) {
  return (
          <FadeIn delay={0.2} className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                <BookOpen size={14} className="text-indigo-400" />
                ブログ新着
              </h2>
              <Link href="/blog" className="flex items-center gap-1 text-xs text-indigo-300 transition hover:text-indigo-200">
                記事一覧へ <ChevronRight size={12} />
              </Link>
            </div>
            {latestBlogPosts.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4 text-sm text-slate-400">
                記事を準備中です。しばらくしてから
                <Link href="/blog" className="text-indigo-300 hover:text-indigo-200">
                  ブログ一覧
                </Link>
                をご覧ください。
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-3">
                {latestBlogPosts.map((article) => (
                  <Link
                    key={article.slug}
                    href={`/blog/${article.slug}`}
                    className="flex flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/80 text-sm transition hover:border-amber-400/80 hover:bg-slate-900 hover:shadow-[0_0_20px_rgba(251,191,36,0.25)]"
                  >
                    <div className="flex min-h-24 flex-wrap items-center justify-center gap-2 border-b border-slate-800 bg-gradient-to-br from-indigo-900/40 to-slate-900/80 px-3 py-3">
                      <span className="text-center text-[11px] font-medium text-indigo-200/90">
                        {article.categoryLabel}
                      </span>
                      <span className="rounded-full border border-emerald-400/50 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">
                        予測ベース
                      </span>
                    </div>
                    <div className="flex flex-1 flex-col p-3">
                      <p className="text-[10px] text-slate-500">{article.dateLabel}</p>
                      <p className="mt-1 text-sm font-semibold leading-snug text-slate-50">
                        {article.title}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </FadeIn>
  );
}
