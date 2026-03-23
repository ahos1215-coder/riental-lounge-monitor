import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

export type LineLimitResult = { success: boolean };

function envInt(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.min(n, 1_000_000) : fallback;
}

function rateLimitDisabled(): boolean {
  return process.env.LINE_RATE_LIMIT_DISABLED === "1";
}

// --- Optional Upstash (本番・マルチインスタンスで有効) ---

let redisClient: Redis | null = null;
let redisChecked = false;

function getRedis(): Redis | null {
  if (!redisChecked) {
    redisChecked = true;
    const url = process.env.UPSTASH_REDIS_REST_URL?.trim();
    const token = process.env.UPSTASH_REDIS_REST_TOKEN?.trim();
    redisClient = url && token ? new Redis({ url, token }) : null;
    if (!redisClient && process.env.NODE_ENV === "production") {
      console.warn(
        "[line] UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN 未設定: レート制限はプロセス内メモリのみ（サーバレスでは弱い）。本番は Upstash 推奨。",
      );
    }
  }
  return redisClient;
}

let ratelimitGlobal: Ratelimit | null = null;
let ratelimitUserDraft: Ratelimit | null = null;

function getGlobalRatelimit(): Ratelimit | null {
  const redis = getRedis();
  if (!redis) return null;
  if (!ratelimitGlobal) {
    const n = envInt("LINE_WEBHOOK_GLOBAL_PER_MINUTE", 200);
    ratelimitGlobal = new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(n, "1 m"),
      prefix: "meguribi:line:global",
      analytics: false,
    });
  }
  return ratelimitGlobal;
}

function getUserDraftRatelimit(): Ratelimit | null {
  const redis = getRedis();
  if (!redis) return null;
  if (!ratelimitUserDraft) {
    const n = envInt("LINE_WEBHOOK_DRAFT_PER_USER_HOUR", 20);
    ratelimitUserDraft = new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(n, "1 h"),
      prefix: "meguribi:line:draft:user",
      analytics: false,
    });
  }
  return ratelimitUserDraft;
}

// --- メモリフォールバック（開発用・単一プロセス向け） ---

const memGlobalHits: number[] = [];
const memUserDraftHits = new Map<string, number[]>();
let memWarned = false;

function pruneTimestamps(timestamps: number[], windowMs: number): number[] {
  const cut = Date.now() - windowMs;
  return timestamps.filter((t) => t > cut);
}

/**
 * Webhook POST 全体のスループット上限（LINE サーバー経由のため IP ではなく定数キー）。
 * 署名検証成功後に呼ぶこと。
 */
export async function limitLineWebhookGlobal(): Promise<LineLimitResult> {
  if (rateLimitDisabled()) return { success: true };

  const perMinute = envInt("LINE_WEBHOOK_GLOBAL_PER_MINUTE", 200);
  const rl = getGlobalRatelimit();
  if (rl) {
    const { success } = await rl.limit("global");
    return { success };
  }

  if (!memWarned && process.env.NODE_ENV === "development") {
    memWarned = true;
    console.info("[line] rate limit: in-memory fallback（Upstash 未設定）");
  }

  const windowMs = 60_000;
  const now = Date.now();
  const next = pruneTimestamps(memGlobalHits, windowMs);
  next.push(now);
  memGlobalHits.length = 0;
  memGlobalHits.push(...next);
  return { success: next.length <= perMinute };
}

/**
 * 下書きパイプライン（Gemini / range）のユーザーあたり上限。
 */
export async function limitLineUserDraft(userId: string | null | undefined): Promise<LineLimitResult> {
  if (rateLimitDisabled()) return { success: true };

  const key = (userId && userId.trim()) || "anonymous";
  const perHour = envInt("LINE_WEBHOOK_DRAFT_PER_USER_HOUR", 20);
  const rl = getUserDraftRatelimit();
  if (rl) {
    const { success } = await rl.limit(key);
    return { success };
  }

  const windowMs = 3_600_000;
  const now = Date.now();
  const prev = memUserDraftHits.get(key) ?? [];
  const next = pruneTimestamps(prev, windowMs);
  next.push(now);

  if (memUserDraftHits.size > 5_000) {
    memUserDraftHits.clear();
  }
  memUserDraftHits.set(key, next);

  return { success: next.length <= perHour };
}
