import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";

import { parseLineIntent } from "@/lib/line/parseLineIntent";
import { runBlogDraftPipeline } from "@/lib/blog/runBlogDraftPipeline";
import { limitLineUserDraft, limitLineWebhookGlobal } from "@/lib/rateLimit/lineWebhookLimits";
import {
  publishEditorialByFactsId,
  publishEditorialBySlug,
  fetchLatestUnpublishedEditorialByLineUser,
} from "@/lib/supabase/blogDrafts";

/** Flask backend base URL (same as other Next API proxies). */
// Vercel 側で `BACKEND-URL` として登録されてしまうケースがあるため、保険で別名も許容する。
const BACKEND_URL =
  process.env.BACKEND_URL ??
  process.env["BACKEND-URL"] ??
  "http://127.0.0.1:5000";

/**
 * Range fetch limit（`/api/range` は `store` + `limit` のみ）。
 * 旧 20 行では夜窓内サンプルが極端に少なくインサイトが偏るため、既定は定時 Cron（`BLOG_CRON_RANGE_LIMIT`）と揃え 500。
 * 負荷試験時のみ `LINE_RANGE_LIMIT` で下げる。
 */
function lineRangeLimit(): number {
  const raw = process.env.LINE_RANGE_LIMIT?.trim();
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  if (Number.isFinite(n) && n > 0) return Math.min(n, 50_000);
  return 500;
}

export const maxDuration = 60;

type LineWebhookBody = {
  destination?: string;
  events?: LineEvent[];
};

type LineEvent = {
  type?: string;
  message?: { type?: string; id?: string; text?: string };
  source?: { userId?: string; type?: string };
  replyToken?: string;
  webhookEventId?: string;
};

function verifyLineSignature(rawBody: string, signature: string | null, secret: string): boolean {
  if (!signature) return false;
  const expected = crypto.createHmac("sha256", secret).update(rawBody).digest();
  let received: Buffer;
  try {
    received = Buffer.from(signature, "base64");
  } catch {
    return false;
  }
  if (expected.length !== received.length) return false;
  return crypto.timingSafeEqual(expected, received);
}

async function replyLine(replyToken: string, text: string): Promise<void> {
  const token = process.env.LINE_CHANNEL_ACCESS_TOKEN?.trim();
  if (!token) {
    console.warn("[line] LINE_CHANNEL_ACCESS_TOKEN not set; skip reply");
    return;
  }

  const body = {
    replyToken,
    messages: [{ type: "text" as const, text: truncate(text, 4800) }],
  };

  const res = await fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errTxt = await res.text();
    console.error("[line] reply failed", res.status, errTxt.slice(0, 300));
  }
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 20)}\n…(省略)`;
}

function siteBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_BASE_URL?.replace(/\/$/, "") ||
    "https://www.meguribi.jp"
  );
}

function helpText(): string {
  return [
    "【MEGRIBI レポートボット】",
    "",
    "■ 予報下書きを作る",
    "　店舗名と任意で日付・トピックを送ってください。",
    "　例: 渋谷 / 新宿 今夜 / shibuya 2025-12-21",
    "",
    "■ 分析レポートを依頼する",
    "　「〇〇を分析して」「〇〇のレポート」「〇〇を比較して」",
    "　例: 渋谷 先週と比較して / 福岡を分析して",
    "",
    "■ 月間まとめ",
    "　「〇〇 月間まとめ」「〇〇 今月のレポート」",
    "　例: 渋谷 月間まとめ / 新宿 先月のレポート",
    "",
    "■ エリア比較",
    "　「〇〇 エリア比較」で同地域の店舗と比較分析",
    "　例: 渋谷 エリア比較",
    "",
    "■ 分析記事を公開する",
    "　「公開」「ok」「承認」を送ると直近の未公開記事が公開されます。",
    "　例: 公開 / ok / 〇〇-slug を公開",
    "",
    "日付を省略すると今日（日本時間）です。",
  ].join("\n");
}

async function handleApproveIntent(
  replyToken: string,
  lineUserId: string | null,
  targetSlug: string | null,
): Promise<void> {
  // slug 指定がある場合はそちらを優先
  if (targetSlug) {
    const result = await publishEditorialBySlug(targetSlug);
    if (!result.ok) {
      await replyLine(replyToken, `公開に失敗しました。\n${result.error}`);
      return;
    }
    const url = `${siteBaseUrl()}/blog/${encodeURIComponent(result.publicSlug)}`;
    await replyLine(replyToken, `公開しました！\n${url}`);
    return;
  }

  // slug 指定なし → LINE ユーザーの直近の未公開 editorial を探す
  if (!lineUserId) {
    await replyLine(replyToken, "承認対象を特定できません（user ID 不明）。slug を指定して送ってください。");
    return;
  }

  const draft = await fetchLatestUnpublishedEditorialByLineUser(lineUserId);
  if (!draft) {
    await replyLine(replyToken, "承認できる未公開の分析記事が見つかりませんでした。");
    return;
  }

  const result = await publishEditorialByFactsId(draft.facts_id);
  if (!result.ok) {
    await replyLine(replyToken, `公開に失敗しました。\n${result.error}`);
    return;
  }

  const slug = result.publicSlug ?? draft.public_slug ?? draft.facts_id;
  const url = `${siteBaseUrl()}/blog/${encodeURIComponent(slug)}`;
  await replyLine(
    replyToken,
    `${draft.store_slug}（${draft.target_date}）の記事を公開しました！\n${url}`,
  );
}

async function handleDraftOrEditorialIntent(
  replyToken: string,
  lineUserId: string | null,
  intent: {
    kind: "draft" | "editorial_analysis";
    store: import("@/app/config/stores").StoreMeta;
    dateYmd: string;
    factsId: string;
    topicHint: string;
    scope?: import("@/lib/line/parseLineIntent").AnalysisScope;
    compareStores?: import("@/app/config/stores").StoreMeta[];
  },
): Promise<void> {
  const userLimit = await limitLineUserDraft(lineUserId);
  if (!userLimit.success) {
    await replyLine(
      replyToken,
      "生成は短時間の上限に達しました。しばらく（目安: 1時間）してから再度お試しください。",
    );
    return;
  }

  try {
    // スコープに応じた topicHint の拡張
    let enrichedTopicHint = intent.topicHint;
    if (intent.scope === "monthly") {
      enrichedTopicHint = `月間まとめ分析。${intent.topicHint}`.trim();
    } else if (intent.scope === "area_compare" && intent.compareStores?.length) {
      const names = intent.compareStores.map((s) => s.label).join("・");
      enrichedTopicHint = `エリア比較分析（${names}との比較）。${intent.topicHint}`.trim();
    }

    console.log("[line] Running pipeline", { kind: intent.kind, slug: intent.store.slug, scope: intent.scope });
    const result = await runBlogDraftPipeline({
      backendUrl: BACKEND_URL,
      rangeLimit: intent.scope === "monthly" ? Math.min(lineRangeLimit() * 4, 5000) : lineRangeLimit(),
      store: intent.store,
      dateYmd: intent.dateYmd,
      factsId: intent.factsId,
      topicHint: enrichedTopicHint,
      source: "line_webhook",
      lineUserId,
    });

    if (!result.ok) {
      await replyLine(replyToken, `処理中にエラーが発生しました。\n${truncate(result.error, 800)}`);
      return;
    }

    const { insightResult } = result;
    console.log("[line] Pipeline ok", {
      kind: intent.kind,
      source: insightResult.source,
      crowd_label: insightResult.insight.crowd_label,
    });

    let suffix = "";
    if (intent.kind === "editorial_analysis") {
      suffix = [
        "",
        "----",
        "分析記事として保存しました（未公開）。",
        "内容を確認後、「公開」と送ると公開URLが発行されます。",
      ].join("\n");
    }

    await replyLine(replyToken, result.summaryLines.join("\n") + suffix);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[line] pipeline error", msg);
    await replyLine(replyToken, `処理中にエラーが発生しました。\n${truncate(msg, 800)}`);
  }
}

async function processMessageEvent(ev: LineEvent): Promise<void> {
  const replyToken = ev.replyToken;
  if (!replyToken) return;

  const text = ev.message?.type === "text" ? ev.message.text?.trim() : "";
  console.log("[line] Extracted text:", text);
  if (!text) {
    await replyLine(replyToken, "テキストメッセージのみ対応しています。");
    return;
  }

  const intent = parseLineIntent(text);
  console.log("[line] Intent kind:", intent.kind);

  if (intent.kind === "help") {
    await replyLine(replyToken, helpText());
    return;
  }
  if (intent.kind === "error") {
    console.log("[line] Intent error:", intent.message);
    await replyLine(replyToken, intent.message);
    return;
  }

  const lineUserId = ev.source?.userId ?? null;

  if (intent.kind === "approve") {
    await handleApproveIntent(replyToken, lineUserId, intent.targetSlug);
    return;
  }

  // draft / editorial_analysis
  await handleDraftOrEditorialIntent(replyToken, lineUserId, intent);
}

async function handleWebhookBody(rawBody: string): Promise<void> {
  let body: LineWebhookBody;
  try {
    body = JSON.parse(rawBody) as LineWebhookBody;
  } catch {
    console.error("[line] invalid JSON body");
    return;
  }

  const events = body.events ?? [];
  for (const ev of events) {
    console.log("[line] Received event:", JSON.stringify(ev, null, 2));
    if (ev.type !== "message") continue;
    await processMessageEvent(ev);
  }
}

export async function GET() {
  return NextResponse.json({ ok: true, service: "line-webhook" });
}

export async function POST(req: NextRequest) {
  const rawBody = await req.text();

  const secret = process.env.LINE_CHANNEL_SECRET?.trim();
  if (process.env.NODE_ENV === "development") {
    console.log("[line] env presence", {
      hasLINE_CHANNEL_SECRET: Boolean(secret),
      hasLINE_CHANNEL_ACCESS_TOKEN: Boolean(process.env.LINE_CHANNEL_ACCESS_TOKEN?.trim()),
      hasGEMINI_API_KEY: Boolean(process.env.GEMINI_API_KEY?.trim()),
      hasSUPABASE_URL: Boolean(process.env.SUPABASE_URL?.trim()),
      hasSUPABASE_SERVICE_ROLE_KEY: Boolean(
        process.env.SUPABASE_SERVICE_ROLE_KEY?.trim() || process.env.SUPABASE_SERVICE_KEY?.trim()
      ),
      backendUrlIsFallback: BACKEND_URL === "http://127.0.0.1:5000",
    });
  }
  const forceSkip =
    process.env.NODE_ENV === "development" && process.env.SKIP_LINE_SIGNATURE_VERIFY === "1";
  const devWithoutSecret = process.env.NODE_ENV === "development" && !secret;
  const skipVerify = forceSkip || devWithoutSecret;

  if (!skipVerify) {
    if (!secret) {
      return NextResponse.json({ ok: false, error: "line-not-configured" }, { status: 503 });
    }
    const sig = req.headers.get("x-line-signature");
    if (!verifyLineSignature(rawBody, sig, secret)) {
      return NextResponse.json({ ok: false, error: "invalid-signature" }, { status: 401 });
    }
  }

  const globalLimit = await limitLineWebhookGlobal();
  if (!globalLimit.success) {
    console.warn("[line] global rate limit exceeded; skip processing (200 OK for LINE)");
    return new NextResponse("OK", { status: 200 });
  }

  // Vercel serverless 上で `after()` がサスペンドされ、返信処理まで完遂されないケースがあるため、
  // ここでは webhook 完了まで同期的に待つ（LINE には 200 を返す）。
  try {
    await handleWebhookBody(rawBody);
  } catch (err) {
    console.error("[line] POST handleWebhookBody failed", err);
  }

  return new NextResponse("OK", { status: 200 });
}
