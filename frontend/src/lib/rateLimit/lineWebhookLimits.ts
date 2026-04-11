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

// Upstash が連続して失敗した場合の circuit breaker。
// archive / network 障害時に毎リクエスト Redis に当たって LINE webhook が
// 500 を返すのを防ぐため、一度失敗したら一定時間は in-memory フォールバックに切り替える。
const UPSTASH_FAILURE_BACKOFF_MS = 5 * 60 * 1000; // 5 分
let upstashDisabledUntil = 0;
let upstashFailureWarned = false;

function isUpstashTemporarilyDisabled(): boolean {
  return Date.now() < upstashDisabledUntil;
}

function disableUpstashTemporarily(reason: unknown): void {
  upstashDisabledUntil = Date.now() + UPSTASH_FAILURE_BACKOFF_MS;
  if (!upstashFailureWarned) {
    upstashFailureWarned = true;
    console.warn(
      "[line] Upstash rate limit error; falling back to in-memory limiter for ~5 min. " +
        "If this persists, the meguribi-redis instance may be archived/deleted — " +
        "remove UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN from Vercel env. detail=",
      reason instanceof Error ? reason.message : String(reason),
    );
  }
}

function getGlobalRatelimit(): Ratelimit | null {
  if (isUpstashTemporarilyDisabled()) return null;
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
  if (isUpstashTemporarilyDisabled()) return null;
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

function memGlobalCheck(perMinute: number): LineLimitResult {
  if (!memWarned && process.env.NODE_ENV === "development") {
    memWarned = true;
    console.info("[line] rate limit: in-memory fallback（Upstash 未設定 or 障害中）");
  }
  const windowMs = 60_000;
  const now = Date.now();
  const next = pruneTimestamps(memGlobalHits, windowMs);
  next.push(now);
  memGlobalHits.length = 0;
  memGlobalHits.push(...next);
  return { success: next.length <= perMinute };
}

function memUserDraftCheck(key: string, perHour: number): LineLimitResult {
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

/**
 * Webhook POST 全体のスループット上限（LINE サーバー経由のため IP ではなく定数キー）。
 * 署名検証成功後に呼ぶこと。Upstash 障害時は in-memory フォールバック。
 */
export async function limitLineWebhookGlobal(): Promise<LineLimitResult> {
  if (rateLimitDisabled()) return { success: true };

  const perMinute = envInt("LINE_WEBHOOK_GLOBAL_PER_MINUTE", 200);
  const rl = getGlobalRatelimit();
  if (rl) {
    try {
      const { success } = await rl.limit("global");
      return { success };
    } catch (err) {
      // Upstash が archive されている / ネットワーク障害 / 認証エラー等
      // → in-memory フォールバックで LINE webhook を継続稼働させる
      disableUpstashTemporarily(err);
      return memGlobalCheck(perMinute);
    }
  }

  return memGlobalCheck(perMinute);
}

/**
 * 下書きパイプライン（Gemini / range）のユーザーあたり上限。
 * Upstash 障害時は in-memory フォールバック。
 */
export async function limitLineUserDraft(userId: string | null | undefined): Promise<LineLimitResult> {
  if (rateLimitDisabled()) return { success: true };

  const key = (userId && userId.trim()) || "anonymous";
  const perHour = envInt("LINE_WEBHOOK_DRAFT_PER_USER_HOUR", 20);
  const rl = getUserDraftRatelimit();
  if (rl) {
    try {
      const { success } = await rl.limit(key);
      return { success };
    } catch (err) {
      disableUpstashTemporarily(err);
      return memUserDraftCheck(key, perHour);
    }
  }

  return memUserDraftCheck(key, perHour);
}
