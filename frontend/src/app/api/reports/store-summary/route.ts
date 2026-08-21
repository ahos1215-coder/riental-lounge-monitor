import { NextResponse } from "next/server";
import { fetchLatestPublishedReportByStoreWithStatus } from "@/lib/supabase/blogDrafts";
import { extractBullets, extractFirstHeading, stripFrontmatter } from "@/lib/blog/mdx";

import { formatJstLabel as _fmtJst } from "@/lib/dateFormat";

function formatJstLabel(iso: string | undefined): string {
  if (!iso) return "—";
  const r = _fmtJst(iso);
  return r === "-" ? "—" : r;
}

/** AIレポートは 1日2回更新 (18:00/21:30 Daily, 毎週水曜 Weekly) — 10分 CDN + 30分 stale */
const CACHE_HEADER = "public, s-maxage=600, stale-while-revalidate=1800";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const store = (url.searchParams.get("store") ?? "").trim().toLowerCase();

  if (!store) {
    return NextResponse.json({ ok: false, error: "store is required" }, { status: 400 });
  }

  // /store/[id] からの Daily Report カードは v2 (2026-04-23) で削除済み。
  // このエンドポイントは現在 weekly のみを使うため daily の Supabase クエリを省略する。
  // 後方互換のため `daily: null` をレスポンスに残す。
  const { row: weeklyRow, failed } = await fetchLatestPublishedReportByStoreWithStatus(
    store,
    "weekly",
  );

  // 取得できなかったときに「この店には週報がありません」と偽らない（F11 と同じ扱い）。
  // 設定不備・Supabase 障害はここに来る。エラーを CDN に焼き付けないよう no-store。
  if (failed) {
    return NextResponse.json(
      { ok: false, error: "reports-unavailable" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  const weekly = weeklyRow
    ? {
        bullets: extractBullets(weeklyRow.mdx_content, 3),
        heading: extractFirstHeading(stripFrontmatter(weeklyRow.mdx_content), {
          // 空白だけの見出しで "" を返す従来挙動（レスポンス値を変えないため false 固定）
          skipBlank: false,
        }),
        updatedAt: formatJstLabel(weeklyRow.updated_at ?? weeklyRow.created_at),
        targetDate: weeklyRow.target_date ?? "—",
      }
    : null;

  return NextResponse.json(
    { ok: true, daily: null, weekly },
    {
      status: 200,
      headers: { "cache-control": CACHE_HEADER },
    },
  );
}
