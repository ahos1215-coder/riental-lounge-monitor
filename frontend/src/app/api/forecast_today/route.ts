import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:5000";

// 対応店舗 ID 型（将来ここに増やしていく）
export type StoreId = "nagasaki";

const DEFAULT_STORE: StoreId = "nagasaki";

type ErrorBody = {
  ok: false;
  error: string;
  detail?: string;
};

function resolveStore(searchParams: URLSearchParams): StoreId {
  const raw = searchParams.get("store");
  if (!raw) return DEFAULT_STORE;

  if (raw === "nagasaki") {
    return raw;
  }

  console.warn(
    `api/forecast_today: unknown store "${raw}", fallback to "${DEFAULT_STORE}"`
  );
  return DEFAULT_STORE;
}

function backendError(detail: string) {
  const body: ErrorBody = {
    ok: false,
    error: "backend-error",
    detail,
  };
  return NextResponse.json(body, { status: 502 });
}

function unexpectedError(detail: string) {
  const body: ErrorBody = {
    ok: false,
    error: "unexpected-error",
    detail,
  };
  return NextResponse.json(body, { status: 500 });
}

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const store = resolveStore(searchParams);

    const apiUrl = `${BACKEND_URL}/api/forecast_today?store=${encodeURIComponent(
      store
    )}`;

    const res = await fetch(apiUrl);

    if (!res.ok) {
      const detail = `backend responded with status ${res.status}`;
      console.error("api/forecast_today backend error:", detail);
      return backendError(detail);
    }

    const json = await res.json();
    return NextResponse.json(json);
  } catch (err) {
    console.error("api/forecast_today unexpected error:", err);
    return unexpectedError("proxy request failed");
  }
}
