"use client";

import Link from "next/link";
import type { ReportSummaryItem } from "./storePageTypes";

type StoreReportSummarySectionProps = {
  weekly: ReportSummaryItem;
  slug: string;
};

// AI レポート要約セクション（Weekly Report のみ）
export function StoreReportSummarySection({ weekly, slug }: StoreReportSummarySectionProps) {
  return (
    <section className="mx-auto w-full max-w-6xl px-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">AI 予測レポート</h2>
      <div className="grid gap-3">
        {/* Weekly Report */}
        {weekly && (
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center rounded-md bg-amber-500/20 px-2 py-0.5 text-[11px] font-bold text-amber-200">
                Weekly Report
              </span>
              <span className="text-[11px] text-white/40">{weekly.updatedAt} 更新</span>
            </div>
            {weekly.heading && (
              <p className="mt-2 text-sm font-bold leading-snug text-white line-clamp-2">
                {weekly.heading}
              </p>
            )}
            {weekly.bullets.length > 0 && (
              <ul className="mt-2 space-y-1">
                {weekly.bullets.map((b, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-white/75">
                    <span className="mt-0.5 shrink-0 text-amber-300">▸</span>
                    <span className="line-clamp-2">{b}</span>
                  </li>
                ))}
              </ul>
            )}
            <Link
              href={`/reports/weekly/${encodeURIComponent(slug)}`}
              className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-amber-300 hover:text-amber-200"
            >
              詳しく見る <span aria-hidden>→</span>
            </Link>
          </div>
        )}
      </div>
      <div className="mt-3">
        <Link
          href="/reports"
          className="text-xs text-indigo-300 hover:text-indigo-200"
        >
          AI予測レポート一覧 →
        </Link>
      </div>
    </section>
  );
}
