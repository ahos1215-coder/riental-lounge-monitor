import { NextRequest, NextResponse } from "next/server";
import { DEFAULT_STORE } from "../../config/stores";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

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
  const { searchParams } = new URL(req.url);
  const store = resolveStore(searchParams);

  const base = BACKEND_URL.replace(/\/+$/, "");
  const apiUrl = `${base}/api/forecast_next_hour?store=${encodeURIComponent(
    store
  )}`;

  try {
    const backendRes = await fetch(apiUrl, { next: { revalidate: 0 } });
    const buf = await backendRes.arrayBuffer();

    const headers = new Headers();
    const contentType = backendRes.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    }

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
