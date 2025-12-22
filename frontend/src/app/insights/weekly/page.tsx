import type { Metadata } from "next";
import Link from "next/link";
import fs from "node:fs/promises";
import path from "node:path";

export const metadata: Metadata = {
  title: "週間Insights | めぐりび",
  description: "週次のGood Window Insightsを表示します。",
};

type StoreEntry = {
  latest_file?: string;
  generated_at?: string;
};

type IndexPayload = {
  generated_at?: string;
  stores?: Record<string, StoreEntry>;
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

export default async function WeeklyInsightsIndexPage() {
  const { data, error } = await readIndex();
  const stores = data?.stores && isRecord(data.stores) ? Object.entries(data.stores) : [];

  return (
    <main className="relative min-h-[calc(100vh-80px)] bg-black text-white">
      <div className="relative mx-auto w-full max-w-5xl px-4 pb-16 pt-10">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-black tracking-tight">週次Insights</h1>
            <p className="mt-2 text-sm text-white/60">
              Good Window Explorer（最小版）の週次サマリーです。
            </p>
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-xs text-white/50">generated_at</p>
          <p className="mt-1 text-sm font-semibold">{data?.generated_at ?? "-"}</p>
        </div>

        {error ? (
          <div className="mt-6 rounded-2xl border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
            {error}
          </div>
        ) : stores.length === 0 ? (
          <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-white/70">
            表示できる店舗がありません。index.json を確認してください。
          </div>
        ) : (
          <section className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {stores.map(([store, meta]) => (
              <Link
                key={store}
                href={`/insights/weekly/${store}`}
                className="group rounded-2xl border border-white/10 bg-white/5 p-5 hover:border-white/20"
              >
                <p className="text-xs text-white/50">store</p>
                <p className="mt-1 text-lg font-black">{store}</p>
                <p className="mt-3 text-xs text-white/50">latest_file</p>
                <p className="text-sm text-white/80">{meta?.latest_file ?? "-"}</p>
                <p className="mt-3 text-xs text-white/50">generated_at</p>
                <p className="text-sm text-white/80">{meta?.generated_at ?? "-"}</p>
              </Link>
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
