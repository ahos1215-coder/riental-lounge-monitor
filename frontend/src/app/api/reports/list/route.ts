import { NextResponse } from "next/server";
import {
  fetchAllLatestPublishedReports,
  isBlogDraftsConfigured,
  type PublishedReportType,
} from "@/lib/supabase/blogDrafts";

const CACHE_HEADER = "public, s-maxage=300, stale-while-revalidate=900";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const raw = url.searchParams.get("type") ?? "daily";
  const contentType: PublishedReportType = raw === "weekly" ? "weekly" : "daily";

  if (!isBlogDraftsConfigured()) {
    return NextResponse.json(
      { ok: true, data: [] },
      { status: 200, headers: { "cache-control": CACHE_HEADER } },
    );
  }

  const items = await fetchAllLatestPublishedReports(contentType, 50);
  return NextResponse.json(
    { ok: true, data: items },
    { status: 200, headers: { "cache-control": CACHE_HEADER } },
  );
}
