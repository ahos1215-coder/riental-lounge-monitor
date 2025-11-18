import { NextRequest, NextResponse } from "next/server";

const ALLOWED_STORES = ["nagasaki"] as const;
export type StoreId = (typeof ALLOWED_STORES)[number];

type ApiErrorBody = {
  ok: false;
  message: string;
  detail?: string;
};

export function parseStore(req: NextRequest): StoreId | null {
  const store = req.nextUrl.searchParams.get("store");

  // store 指定がない場合は、ひとまず nagasaki をデフォルトにする
  if (!store) {
    return ALLOWED_STORES[0];
  }

  if (ALLOWED_STORES.includes(store as StoreId)) {
    return store as StoreId;
  }

  return null;
}

export function errorResponse(
  status: number,
  message: string,
  detail?: string
) {
  const body: ApiErrorBody = {
    ok: false,
    message,
    ...(detail ? { detail } : {}),
  };
  return NextResponse.json(body, { status });
}

export async function proxyForecast(kind: "next_hour" | "today", store: StoreId) {
  const backend = process.env.BACKEND_URL;

  if (!backend) {
    return errorResponse(500, "BACKEND_URL is not set");
  }

  const base = backend.replace(/\/+$/, "");
  const url = `${base}/api/forecast_${kind}?store=${encodeURIComponent(store)}`;

  try {
    const res = await fetch(url, {
      // キャッシュさせず、毎回取りに行く
      next: { revalidate: 0 },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return errorResponse(
        502,
        `backend error: ${res.status}`,
        text ? text.slice(0, 500) : undefined
      );
    }

    const json = await res.json();
    // バックエンドのレスポンス（ok/dataなど）はそのまま返す
    return NextResponse.json(json);
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : typeof err === "string" ? err : "";
    return errorResponse(502, "failed to fetch backend", detail || undefined);
  }
}
