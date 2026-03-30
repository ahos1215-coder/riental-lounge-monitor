import { NextRequest, NextResponse } from "next/server";
import { rateLimit, rateLimitHeaders } from "@/lib/rateLimit/apiRateLimit";
import { DEFAULT_STORE } from "../../config/stores";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** 予測モデルは15分ごとに再計算 → 5分CDNキャッシュ、15分stale-while-revalidate */
const CACHE_HEADER = "public, s-maxage=300, stale-while-revalidate=900";

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
  const rl = await rateLimit(req, "forecast_today", 30);
  if (!rl.success) return new NextResponse("Too Many Requests", { status: 429, headers: rateLimitHeaders(rl) });
  const { searchParams } = new URL(req.url);
  const store = resolveStore(searchParams);

  const base = BACKEND_URL.replace(/\/+$/, "");
  const apiUrl = `${base}/api/forecast_today?store=${encodeURIComponent(store)}`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 300 } });
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
