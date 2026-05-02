import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

/** 連休判定は日付単位で固定なので 1 時間程度キャッシュして十分 */
const CACHE_HEADER = "public, s-maxage=3600, stale-while-revalidate=7200";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const dateParam = url.searchParams.get("date");

  const base = BACKEND_URL.replace(/\/+$/, "");
  const qs = dateParam ? `?date=${encodeURIComponent(dateParam)}` : "";
  const apiUrl = `${base}/api/holiday_status${qs}`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 3600 } });
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
    return NextResponse.json(
      { ok: false, error: "proxy-error", detail },
      { status: 502 },
    );
  }
}
