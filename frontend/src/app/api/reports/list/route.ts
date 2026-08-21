import { NextResponse } from "next/server";
import {
  fetchAllLatestPublishedReports,
  type PublishedReportType,
} from "@/lib/supabase/blogDrafts";

const CACHE_HEADER = "public, s-maxage=300, stale-while-revalidate=900";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const raw = url.searchParams.get("type") ?? "daily";
  const contentType: PublishedReportType = raw === "weekly" ? "weekly" : "daily";

  const { items, failed } = await fetchAllLatestPublishedReports(contentType);

  // 障害（Supabase 未設定 / HTTP エラー / 非配列 JSON / ネットワーク例外）を
  // 「0件」として 200 で返さない。空と障害が区別できないと、利用者には
  // 「レポートがまだありません」と嘘の案内が出て、外形監視も気づけない
  // （2026-08-21 外部レビュー F11）。失敗レスポンスは CDN にも載せない。
  if (failed) {
    return NextResponse.json(
      { ok: false, error: "reports_unavailable" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  return NextResponse.json(
    { ok: true, data: items },
    { status: 200, headers: { "cache-control": CACHE_HEADER } },
  );
}
