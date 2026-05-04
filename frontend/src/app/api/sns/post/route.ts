import crypto from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

const ALLOWED_STORE_SLUGS = new Set([
  "nagasaki",
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

/**
 * X API v2 OAuth 1.0a — User Context でツイートを投稿する。
 * 必要な環境変数:
 *   X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
 */
function xApiConfigured(): boolean {
  return Boolean(
    process.env.X_API_KEY?.trim() &&
    process.env.X_API_SECRET?.trim() &&
    process.env.X_ACCESS_TOKEN?.trim() &&
    process.env.X_ACCESS_TOKEN_SECRET?.trim(),
  );
}

function oauthSign(
  method: string,
  url: string,
  params: Record<string, string>,
  consumerSecret: string,
  tokenSecret: string,
): string {
  const sortedKeys = Object.keys(params).sort();
  const paramString = sortedKeys.map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join("&");
  const baseString = `${method}&${encodeURIComponent(url)}&${encodeURIComponent(paramString)}`;
  const signingKey = `${encodeURIComponent(consumerSecret)}&${encodeURIComponent(tokenSecret)}`;
  return crypto.createHmac("sha1", signingKey).update(baseString).digest("base64");
}

function buildOAuthHeader(method: string, url: string, _body: string): string {
  const apiKey = process.env.X_API_KEY!.trim();
  const apiSecret = process.env.X_API_SECRET!.trim();
  const accessToken = process.env.X_ACCESS_TOKEN!.trim();
  const tokenSecret = process.env.X_ACCESS_TOKEN_SECRET!.trim();

  const nonce = crypto.randomBytes(16).toString("hex");
  const timestamp = Math.floor(Date.now() / 1000).toString();

  const oauthParams: Record<string, string> = {
    oauth_consumer_key: apiKey,
    oauth_nonce: nonce,
    oauth_signature_method: "HMAC-SHA1",
    oauth_timestamp: timestamp,
    oauth_token: accessToken,
    oauth_version: "1.0",
  };

  const signature = oauthSign(method, url, oauthParams, apiSecret, tokenSecret);
  oauthParams.oauth_signature = signature;

  const headerParts = Object.keys(oauthParams)
    .sort()
    .map((k) => `${encodeURIComponent(k)}="${encodeURIComponent(oauthParams[k])}"`)
    .join(", ");

  return `OAuth ${headerParts}`;
}

async function postTweet(text: string): Promise<{ ok: boolean; tweetId?: string; error?: string }> {
  const url = "https://api.x.com/2/tweets";
  const bodyStr = JSON.stringify({ text });
  const authHeader = buildOAuthHeader("POST", url, bodyStr);

  const MAX_RETRIES = 3;
  const BACKOFF = [2000, 5000, 10000];
  const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: authHeader,
          "Content-Type": "application/json",
        },
        body: bodyStr,
      });

      if (res.ok) {
        const json = (await res.json()) as { data?: { id?: string } };
        return { ok: true, tweetId: json.data?.id };
      }

      if (RETRY_STATUS.has(res.status) && attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, BACKOFF[attempt] ?? 10000));
        continue;
      }

      const errText = await res.text().catch(() => "");
      return { ok: false, error: `X API ${res.status}: ${errText.slice(0, 200)}` };
    } catch (err) {
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, BACKOFF[attempt] ?? 10000));
        continue;
      }
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
  }

  return { ok: false, error: "max_retries_exceeded" };
}

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

  const postText = `${body.title ? `${body.title}\n` : ""}${blogUrl}`;
  const dryRun = body.dry_run !== false;

  if (dryRun || !xApiConfigured()) {
    return NextResponse.json({
      ok: true,
      mode: dryRun ? "dry_run" : "x_api_not_configured",
      store_slug: storeSlug,
      post_text_preview: postText,
      note: dryRun
        ? "dry_run=true なので投稿しません。"
        : "X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET を設定すると実投稿できます。",
    });
  }

  const result = await postTweet(postText);

  if (!result.ok) {
    return NextResponse.json({
      ok: false,
      error: "x_post_failed",
      detail: result.error,
      store_slug: storeSlug,
      post_text_preview: postText,
    }, { status: 502 });
  }

  return NextResponse.json({
    ok: true,
    mode: "posted",
    store_slug: storeSlug,
    tweet_id: result.tweetId,
    post_text_preview: postText,
  });
}
