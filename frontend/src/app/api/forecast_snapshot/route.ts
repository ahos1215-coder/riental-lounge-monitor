import { NextRequest, NextResponse } from "next/server";
import { rateLimit, rateLimitHeaders } from "@/lib/rateLimit/apiRateLimit";
import { DEFAULT_STORE } from "../../config/stores";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/**
 * 完了済みの夜（過去日）に配信されていた予測のスナップショット。/api/forecast_today
 * と違い、対象の夜が終わればもう内容は変わらない（scripts/snapshot_forecasts.py が
 * その夜の開始前に一度だけ書き込む）ので、長め＆不変寄りの CDN キャッシュにする。
 */
const CACHE_HEADER = "public, s-maxage=86400, stale-while-revalidate=604800";

type ErrorBody = {
  ok: false;
  error: string;
  detail?: string;
};

function resolveStore(searchParams: URLSearchParams): string {
  const raw = searchParams.get("store");
  return (raw && raw.trim()) || DEFAULT_STORE;
}

export async function GET(req: NextRequest) {
  const rl = await rateLimit(req, "forecast_snapshot", 30);
  if (!rl.success) return new NextResponse("Too Many Requests", { status: 429, headers: rateLimitHeaders(rl) });
  const { searchParams } = new URL(req.url);
  const store = resolveStore(searchParams);
  const date = (searchParams.get("date") ?? "").trim();

  const base = BACKEND_URL.replace(/\/+$/, "");
  const apiUrl =
    `${base}/api/forecast_snapshot?store=${encodeURIComponent(store)}` +
    `&date=${encodeURIComponent(date)}`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 86400 } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
    if (backendRes.ok) headers.set("cache-control", CACHE_HEADER);

    return new NextResponse(buf, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers,
    });
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    const body: ErrorBody = { ok: false, error: "proxy-error", detail };
    return NextResponse.json(body, { status: 502 });
  }
}
