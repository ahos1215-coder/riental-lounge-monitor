import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import { ReservationLinkCard } from "@/components/ReservationLinkCard";
import { ReportViewTracker } from "@/components/ReportViewTracker";
import WeeklyStoreCharts from "@/components/WeeklyStoreCharts";
import type { SeriesCompactPoint, TopWindowChart } from "@/components/WeeklyStoreCharts";
import { fetchLatestPublishedReportByStore } from "@/lib/supabase/blogDrafts";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

/** 毎週水曜更新 — 5 分ごとに再検証 */
export const revalidate = 300;

type Props = {
  params: Promise<{ store_slug: string }>;
};

function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { store_slug } = await params;
  const meta = getStoreMetaBySlugStrict(store_slug);
  const label = meta ? `オリエンタルラウンジ ${meta.label}` : store_slug;
  const title = `${label} · Weekly Report`;
  const description = `${label} の最新AI週報（毎週水曜更新）を表示します。`;
  const base = getMetadataBaseUrl();
  return {
    title,
    description,
    openGraph: {
      title: `${title} | めぐりび`,
      description,
      url: new URL(`/reports/weekly/${encodeURIComponent(store_slug)}`, base),
      type: "article",
      locale: "ja_JP",
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | めぐりび`,
      description,
    },
  };
}

export default async function WeeklyReportStorePage({ params }: Props) {
  const { store_slug } = await params;
  const store = getStoreMetaBySlugStrict(store_slug);
  if (!store) notFound();

  const row = await fetchLatestPublishedReportByStore(store.slug, "weekly");
  if (!row) notFound();

  const content = stripFrontmatter(row.mdx_content);

  // insight_json から定量データを抽出
  const ij = row.insight_json ?? {};
  const metrics = (ij.metrics ?? {}) as Record<string, unknown>;
  const insightParams = (ij.params ?? {}) as Record<string, unknown>;
  const period = (ij.period ?? {}) as Record<string, unknown>;
  const threshold = typeof insightParams.threshold === "number" ? insightParams.threshold : 0.8;
  const minDuration = typeof insightParams.min_duration_minutes === "number" ? insightParams.min_duration_minutes : 120;
  const reliability = typeof metrics.reliability_score === "number" ? metrics.reliability_score : 0;

  const rawTopWindows = Array.isArray(ij.top_windows) ? ij.top_windows : [];
  const topWindows: TopWindowChart[] = rawTopWindows
    .filter((w): w is Record<string, unknown> => Boolean(w && typeof w === "object"))
    .map((w) => ({
      start: typeof w.start === "string" ? w.start : undefined,
      end: typeof w.end === "string" ? w.end : undefined,
      duration_minutes: typeof w.duration_minutes === "number" ? w.duration_minutes : undefined,
      avg_score: typeof w.avg_score === "number" ? w.avg_score : undefined,
    }));

  const rawSeries = Array.isArray(ij.series_compact) ? ij.series_compact : [];
  const seriesCompact: SeriesCompactPoint[] = rawSeries
    .filter(
      (p): p is { t: string; occupancy: number; female_ratio: number } =>
        typeof p?.t === "string" &&
        typeof p?.occupancy === "number" &&
        Number.isFinite(p.occupancy) &&
        typeof p?.female_ratio === "number" &&
        Number.isFinite(p.female_ratio),
    )
    .map((p) => ({ t: p.t, occupancy: p.occupancy, female_ratio: p.female_ratio }));

  const hasInsightData = seriesCompact.length > 0 || topWindows.length > 0;

  function formatNumber(value: unknown, digits = 2): string {
    if (typeof value !== "number" || Number.isNaN(value)) return "-";
    return value.toFixed(digits);
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <ReportViewTracker storeSlug={store.slug} reportType="weekly" />
      <div className="mb-6 flex flex-wrap gap-4">
        <Link
          href="/reports?tab=weekly"
          className="inline-flex items-center gap-2 text-sm text-white/70 transition hover:text-white"
        >
          <span aria-hidden>←</span>
          AI予測レポート一覧
        </Link>
        <Link
          href={`/store/${store.slug}?store=${store.slug}`}
          className="text-sm text-white/50 transition hover:text-white"
        >
          店舗ページ →
        </Link>
      </div>

      <header className="mb-8">
        <h1 className="text-2xl font-bold leading-tight text-white md:text-3xl">
          {store.label} Weekly Report
        </h1>
        <p className="mt-2 text-sm text-white/60">
          {row.target_date} / 最新更新: {row.created_at ?? "-"}
        </p>
        <p className="mt-4 text-base text-white/75">
          毎週水曜の自動生成で更新される最新週報です。
        </p>
      </header>

      <article className="prose prose-invert mt-10 max-w-none prose-headings:text-white prose-p:text-white/80 prose-li:text-white/80">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </article>

      {hasInsightData && (
        <>
          <hr className="my-10 border-white/10" />

          <section>
            <h2 className="text-xl font-bold text-white">週次データ分析</h2>
            <p className="mt-2 text-sm text-white/60">
              集計期間: {typeof period.start === "string" ? period.start.slice(0, 10) : "-"} 〜{" "}
              {typeof period.end === "string" ? period.end.slice(0, 10) : "-"}
            </p>

            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="text-xs font-medium text-white/70">使用サンプル数</p>
                <p className="mt-2 text-2xl font-black">{typeof metrics.points_used === "number" ? metrics.points_used : 0}</p>
                <p className="mt-1 text-[11px] text-white/40">分析に使ったデータ点数</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="text-xs font-medium text-white/70">ベースライン（p95）</p>
                <p className="mt-2 text-2xl font-black">{formatNumber(metrics.baseline_p95_total, 1)}</p>
                <p className="mt-1 text-[11px] text-white/40">混雑目安の基準値</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="text-xs font-medium text-white/70">信頼度スコア</p>
                <p className="mt-2 text-2xl font-black">{formatNumber(metrics.reliability_score, 2)}</p>
                <p className="mt-1 text-[11px] text-white/40">200点以上で 1.0</p>
                <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all"
                    style={{ width: `${Math.min(100, Math.max(0, reliability * 100))}%` }}
                  />
                </div>
              </div>
            </div>
          </section>

          <div className="mt-8">
            <WeeklyStoreCharts
              store={store.slug}
              series={seriesCompact}
              topWindows={topWindows}
              scoreThreshold={threshold}
            />
          </div>

          {topWindows.length > 0 && (
            <section className="mt-8">
              <h2 className="text-lg font-bold text-white">検出された時間帯（Good Window）</h2>
              <p className="mt-2 text-xs text-white/50">
                スコアが {threshold} 以上が {minDuration} 分続く区間として検出しています。
              </p>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
                {topWindows.map((w, idx) => (
                  <div key={`${w.start ?? "window"}-${idx}`} className="rounded-2xl border border-white/10 bg-black/40 p-5">
                    <p className="text-xs text-white/50">候補 {idx + 1}</p>
                    <p className="mt-2 text-sm text-white/70">
                      <span className="text-white/45">開始:</span> {w.start ?? "-"}
                    </p>
                    <p className="text-sm text-white/70">
                      <span className="text-white/45">終了:</span> {w.end ?? "-"}
                    </p>
                    <p className="mt-2 text-sm text-white/70">
                      <span className="text-white/45">継続時間:</span>{" "}
                      {w.duration_minutes != null ? `${Math.round(w.duration_minutes)} 分` : "-"}
                    </p>
                    <p className="text-sm text-white/70">
                      <span className="text-white/45">平均スコア:</span> {formatNumber(w.avg_score, 3)}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      <div className="mt-10">
        <ReservationLinkCard
          storeName={`オリエンタルラウンジ ${store.label}`}
          storeSlug={store.slug}
          utmCampaign="weekly_report"
        />
      </div>
    </main>
  );
}
