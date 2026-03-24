import crypto from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

const ALLOWED_STORE_SLUGS = new Set([
  "nagasaki",
  // Top5 + 長崎店の運用開始を想定。Top5は環境変数で上書き推奨。
  ...(process.env.SNS_POST_ALLOWED_STORE_SLUGS?.split(",").map((s) => s.trim()).filter(Boolean) ?? []),
]);

function isAuthorized(req: NextRequest): boolean {
  const secret = process.env.SNS_POST_SECRET?.trim();
  if (!secret) return false;
  const auth = req.headers.get("authorization");
  if (!auth) return false;
  const expected = Buffer.from(`Bearer ${secret}`);
  const received = Buffer.from(auth);
  if (expected.length !== received.length) return false;
  return crypto.timingSafeEqual(expected, received);
}

type Payload = {
  store_slug: string;
  blog_url: string;
  title?: string;
  dry_run?: boolean;
};

export async function POST(req: NextRequest) {
  if (!isAuthorized(req)) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  let body: Payload;
  try {
    body = (await req.json()) as Payload;
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const storeSlug = (body.store_slug ?? "").trim().toLowerCase();
  const blogUrl = (body.blog_url ?? "").trim();
  if (!storeSlug || !blogUrl) {
    return NextResponse.json({ ok: false, error: "store_slug and blog_url are required" }, { status: 400 });
  }
  if (!ALLOWED_STORE_SLUGS.has(storeSlug)) {
    return NextResponse.json({ ok: false, error: "store_not_allowed_for_auto_post", store_slug: storeSlug }, { status: 403 });
  }

  // Skeleton only: X API 統合は次フェーズ。dry-runで文面と対象だけ確認する。
  const dryRun = body.dry_run !== false;
  const postText = `${body.title ? `${body.title}\n` : ""}${blogUrl}`;

  return NextResponse.json({
    ok: true,
    mode: dryRun ? "dry_run" : "not_implemented",
    store_slug: storeSlug,
    post_text_preview: postText,
    retry_policy: {
      max_retries: 3,
      backoff_seconds: [2, 5, 10],
      retry_on_status: [429, 500, 502, 503, 504],
    },
    note: "X posting integration will be implemented in the next phase.",
  });
}

