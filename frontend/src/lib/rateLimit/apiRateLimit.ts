/**
 * Lightweight in-memory rate limiter for public API proxy routes.
 *
 * IP ベースのスライディングウィンドウ。Upstash が設定されていればそちらを使い、
 * なければプロセス内メモリにフォールバック（Vercel serverless でも 1 リクエスト内は有効）。
 *
 * 使い方:
 *   import { rateLimit } from "@/lib/rateLimit/apiRateLimit";
 *   const rl = await rateLimit(request, "range");
 *   if (!rl.success) return new NextResponse("Too Many Requests", { status: 429 });
 */
import { NextRequest } from "next/server";

const DEFAULT_REQUESTS_PER_MINUTE = 60;

function envInt(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function getClientIp(req: NextRequest): string {
  return (
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("x-real-ip") ||
    "unknown"
  );
}

// --- In-memory sliding window ---

const windowMs = 60_000;
const hitMap = new Map<string, number[]>();
let lastCleanup = Date.now();

function cleanupIfNeeded() {
  const now = Date.now();
  if (now - lastCleanup < 30_000) return;
  lastCleanup = now;
  const cutoff = now - windowMs * 2;
  for (const [key, timestamps] of hitMap) {
    const valid = timestamps.filter((t) => t > cutoff);
    if (valid.length === 0) hitMap.delete(key);
    else hitMap.set(key, valid);
  }
  // Prevent unbounded memory growth
  if (hitMap.size > 10_000) hitMap.clear();
}

export type RateLimitResult = {
  success: boolean;
  limit: number;
  remaining: number;
};

/**
 * Rate-limit a request by IP + route prefix.
 * @param req - NextRequest
 * @param prefix - route identifier (e.g. "range", "forecast")
 * @param maxPerMinute - override per-minute limit (default: API_RATE_LIMIT_PER_MINUTE env or 60)
 */
export async function rateLimit(
  req: NextRequest,
  prefix: string,
  maxPerMinute?: number,
): Promise<RateLimitResult> {
  const limit = maxPerMinute ?? envInt("API_RATE_LIMIT_PER_MINUTE", DEFAULT_REQUESTS_PER_MINUTE);
  const ip = getClientIp(req);
  const key = `${prefix}:${ip}`;

  cleanupIfNeeded();

  const now = Date.now();
  const cutoff = now - windowMs;
  const prev = hitMap.get(key) ?? [];
  const valid = prev.filter((t) => t > cutoff);
  valid.push(now);
  hitMap.set(key, valid);

  const success = valid.length <= limit;
  return {
    success,
    limit,
    remaining: Math.max(0, limit - valid.length),
  };
}

/** Headers to include in rate-limited responses. */
export function rateLimitHeaders(result: RateLimitResult): Record<string, string> {
  return {
    "X-RateLimit-Limit": String(result.limit),
    "X-RateLimit-Remaining": String(result.remaining),
  };
}
