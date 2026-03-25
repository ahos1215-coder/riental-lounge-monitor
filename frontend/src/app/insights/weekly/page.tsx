import type { Metadata } from "next";
import Link from "next/link";
import fs from "node:fs/promises";
import path from "node:path";
import { getStoreMetaBySlugStrict } from "@/app/config/stores";
import { getMetadataBaseUrl } from "@/lib/siteUrl";

const weeklyBase = getMetadataBaseUrl();

export const metadata: Metadata = {
  title: "週次Insights",
  description:
    "店舗ごとの週次サマリー。混雑が落ち着きやすい時間帯（Good Window）の候補を一覧できます。",
  openGraph: {
    title: "週次Insights | めぐりび",
    description: "店舗別の週次サマリー（Good Window）を一覧します。",
    url: new URL("/insights/weekly", weeklyBase),
    type: "website",
    locale: "ja_JP",
  },
  twitter: {
    card: "summary_large_image",
    title: "週次Insights | めぐりび",
    description: "店舗別の週次サマリー（Good Window）を一覧します。",
  },
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
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/60">
              店舗ごとの1週間分のデータから、混雑が落ち着きやすい時間帯（Good
              Window）の候補をまとめた画面です。詳細は店舗名から開けます。
            </p>
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-xs text-white/50">一覧インデックスの更新時刻</p>
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
            {stores.map(([storeSlug, meta]) => {
              const sm = getStoreMetaBySlugStrict(storeSlug);
              const title = sm ? `オリエンタルラウンジ ${sm.label}` : storeSlug;
              return (
                <Link
                  key={storeSlug}
                  href={`/insights/weekly/${storeSlug}`}
                  className="group rounded-2xl border border-white/10 bg-white/5 p-5 transition hover:border-amber-400/30 hover:bg-white/[0.07]"
                >
                  <p className="text-xs text-white/50">店舗</p>
                  <p className="mt-1 text-lg font-black leading-snug">{title}</p>
                  {sm && (
                    <p className="mt-0.5 text-[11px] text-white/40">slug: {storeSlug}</p>
                  )}
                  <p className="mt-3 text-xs text-white/50">参照中のデータファイル</p>
                  <p className="break-all text-sm text-white/80">{meta?.latest_file ?? "-"}</p>
                  <p className="mt-3 text-xs text-white/50">店舗データの更新時刻</p>
                  <p className="text-sm text-white/80">{meta?.generated_at ?? "-"}</p>
                </Link>
              );
            })}
          </section>
        )}
      </div>
    </main>
  );
}
