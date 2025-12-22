import type { Metadata } from "next";
import Link from "next/link";
import fs from "node:fs/promises";
import path from "node:path";

export const dynamicParams = false;

type StoreEntry = {
  latest_file?: string;
  generated_at?: string;
};

type IndexPayload = {
  generated_at?: string;
  stores?: Record<string, StoreEntry>;
};

type WindowEntry = {
  start?: string;
  end?: string;
  duration_minutes?: number;
  avg_score?: number;
};

type InsightPayload = {
  generated_at?: string;
  period?: { start?: string; end?: string };
  metrics?: {
    points_used?: number;
    baseline_p95_total?: number;
    reliability_score?: number;
  };
  params?: { threshold?: number; min_duration_minutes?: number };
  top_windows?: WindowEntry[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function readIndex(): Promise<{ data: IndexPayload | null; error: string | null }> {
  const indexPath = path.join(process.cwd(), "content", "insights", "weekly", "index.json");
  try {
    const raw = await fs.readFile(indexPath, "utf8");
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) {
      return { data: null, error: "index.json の形式が不正です。" };
    }
    return { data: parsed as IndexPayload, error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { data: null, error: `index.json を読み込めませんでした: ${message}` };
  }
}

async function readInsightFile(store: string, latestFile: string): Promise<{ data: InsightPayload | null; error: string | null }> {
  const filePath = path.join(process.cwd(), "content", "insights", "weekly", store, latestFile);
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) {
      return { data: null, error: "週次JSONの形式が不正です。" };
    }
    return { data: parsed as InsightPayload, error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { data: null, error: `週次JSONを読み込めませんでした: ${message}` };
  }
}

function formatNumber(value: number | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

export async function generateStaticParams(): Promise<Array<{ store: string }>> {
  const { data } = await readIndex();
  const stores = data?.stores && isRecord(data.stores) ? Object.keys(data.stores) : [];
  return stores.map((store) => ({ store }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ store: string }>;
}): Promise<Metadata> {
  const { store } = await params;
  return {
    title: `${store} 週次Insights | めぐりび`,
    description: "Good Window Explorer（最小版）の週次サマリー。",
  };
}

export default async function WeeklyInsightsStorePage({
  params,
}: {
  params: Promise<{ store: string }>;
}) {
  const { store } = await params;
  const { data: indexData, error: indexError } = await readIndex();

  if (indexError) {
    return (
      <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
        <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
          <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
            {indexError}
          </div>
        </div>
      </main>
    );
  }

  const entry = indexData?.stores && isRecord(indexData.stores) ? (indexData.stores[store] as StoreEntry | undefined) : undefined;
  const latestFile = entry?.latest_file;
  if (!latestFile) {
    return (
      <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
        <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
            {store} の最新Insightが見つかりませんでした。
          </div>
        </div>
      </main>
    );
  }

  const { data, error } = await readInsightFile(store, latestFile);

  if (error || !data) {
    return (
      <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
        <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
          <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
            {error ?? "週次JSONが読み込めませんでした。"}
          </div>
        </div>
      </main>
    );
  }

  const metrics = data.metrics ?? {};
  const topWindows = Array.isArray(data.top_windows) ? data.top_windows : [];
  const threshold = data.params?.threshold ?? 0.8;
  const minDuration = data.params?.min_duration_minutes ?? 120;

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
      <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
        <div className="mb-4">
          <Link href="/insights/weekly" className="text-sm text-white/70 hover:text-white">
            ← 週次Insights一覧に戻る
          </Link>
        </div>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs text-white/50">store</p>
            <h1 className="text-2xl font-black tracking-tight">{store}</h1>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-white/70">
            generated_at: {data.generated_at ?? "-"}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <p className="text-xs text-white/50">points_used</p>
            <p className="mt-2 text-2xl font-black">{metrics.points_used ?? 0}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <p className="text-xs text-white/50">baseline_p95_total</p>
            <p className="mt-2 text-2xl font-black">{formatNumber(metrics.baseline_p95_total, 1)}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <p className="text-xs text-white/50">reliability_score</p>
            <p className="mt-2 text-2xl font-black">{formatNumber(metrics.reliability_score, 2)}</p>
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
          period: {data.period?.start ?? "-"} → {data.period?.end ?? "-"}
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-bold">Top Windows</h2>

          {topWindows.length === 0 ? (
            <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
              今週はGood Windowが見つかりませんでした（条件: {threshold}以上が{minDuration}分連続）。
            </div>
          ) : (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
              {topWindows.map((w, idx) => (
                <div key={`${w.start ?? "window"}-${idx}`} className="rounded-2xl border border-white/10 bg-black/40 p-5">
                  <p className="text-xs text-white/50">window #{idx + 1}</p>
                  <p className="mt-2 text-sm text-white/70">start: {w.start ?? "-"}</p>
                  <p className="text-sm text-white/70">end: {w.end ?? "-"}</p>
                  <p className="mt-2 text-sm text-white/70">
                    duration: {w.duration_minutes != null ? Math.round(w.duration_minutes) : "-"} min
                  </p>
                  <p className="text-sm text-white/70">avg_score: {formatNumber(w.avg_score, 3)}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
