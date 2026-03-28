import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** 1分CDNキャッシュ（forecast_today と同じTTL） */
const CACHE_HEADER = "public, s-maxage=60, stale-while-revalidate=300";

type ErrorBody = {
  ok: false;
  error: string;
  detail?: string;
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const stores = searchParams.get("stores") ?? "";

  const base = BACKEND_URL.replace(/\/+$/, "");
  const apiUrl = `${base}/api/forecast_today_multi?stores=${encodeURIComponent(stores)}`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 60 } });
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
