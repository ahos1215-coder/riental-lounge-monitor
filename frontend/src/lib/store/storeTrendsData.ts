import "server-only";

import data from "@/data/storeTrends.generated.json";
import type { StoreTrendEntry } from "./storeTrends";

// scripts/build-store-trends.mjs が事前生成した JSON を静的 import する
// （実行時に Supabase / fs を読まない。Vercel のファイルトレースにも依存しない）。
const stores: Record<string, unknown> = (data as { stores?: Record<string, unknown> }).stores ?? {};

function isEntry(v: unknown): v is StoreTrendEntry {
  if (!v || typeof v !== "object") return false;
  const e = v as Partial<StoreTrendEntry>;
  return (
    Array.isArray(e.weeks) &&
    Array.isArray(e.cells) &&
    typeof e.periodStart === "string" &&
    typeof e.periodEnd === "string"
  );
}

export function getStoreTrendEntry(slug: string): StoreTrendEntry | null {
  if (!Object.prototype.hasOwnProperty.call(stores, slug)) return null;
  const v = stores[slug];
  return isEntry(v) ? v : null;
}
