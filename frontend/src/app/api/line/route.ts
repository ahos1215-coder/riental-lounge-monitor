import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";

import { parseLineIntent } from "@/lib/line/parseLineIntent";
import { buildInsightFromBackend } from "@/lib/blog/insightFromRange";
import { generateBlogDraftMdx } from "@/lib/blog/draftGenerator";
import { insertBlogDraft, isBlogDraftsConfigured } from "@/lib/supabase/blogDrafts";

/** Flask backend base URL (same as other Next API proxies). */
// Vercel 側で `BACKEND-URL` として登録されてしまうケースがあるため、保険で別名も許容する。
const BACKEND_URL =
  process.env.BACKEND_URL ??
  process.env["BACKEND-URL"] ??
  "http://127.0.0.1:5000";

/** Range fetch limit (public contract: store + limit only). */
const RANGE_LIMIT = 20;

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

function helpText(): string {
  return [
    "【MEGRIBI 下書きボット】",
    "店舗名と任意で日付・トピックを送ってください。",
    "",
    "例:",
    "・渋谷",
    "・新宿 今夜",
    "・shibuya 2025-12-21",
    "・ol_shinjuku 2025-12-20 初心者向けに",
    "",
    "日付を省略すると今日（日本時間）です。",
  ].join("\n");
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
  if (intent.kind === "draft") {
    console.log("[line] Intent draft:", {
      storeSlug: intent.store.slug,
      storeLabel: intent.store.label,
      dateYmd: intent.dateYmd,
      factsId: intent.factsId,
      topicHint: intent.topicHint,
    });
  } else if (intent.kind === "error") {
    console.log("[line] Intent error:", intent.message);
  }
  if (intent.kind === "help") {
    await replyLine(replyToken, helpText());
    return;
  }
  if (intent.kind === "error") {
    await replyLine(replyToken, intent.message);
    return;
  }

  const draft = intent;
  const lineUserId = ev.source?.userId ?? null;

  try {
    console.log("[line] Calling backend insight builder");
    const insightResult = await buildInsightFromBackend(
      BACKEND_URL,
      draft.store.slug,
      draft.dateYmd,
      RANGE_LIMIT
    );
    console.log("[line] Backend insight built", {
      source: insightResult.source,
      shift: insightResult.shift,
      crowd_label: insightResult.insight.crowd_label,
      peak_time: insightResult.insight.peak_time,
      avoid_time: insightResult.insight.avoid_time,
    });

    console.log("[line] Calling Gemini draft generator");
    const mdx = await generateBlogDraftMdx({
      storeLabel: draft.store.label,
      storeSlug: draft.store.slug,
      dateYmd: draft.dateYmd,
      factsId: draft.factsId,
      insightResult,
      topicHint: draft.topicHint,
    });

    const insightPayload = {
      facts_id: draft.factsId,
      store: draft.store.slug,
      range: insightResult.range,
      insight: insightResult.insight,
      quality_flags: insightResult.quality_flags,
      source: insightResult.source,
      shift: insightResult.shift,
    };

    let dbNote = "";
    if (isBlogDraftsConfigured()) {
      const ins = await insertBlogDraft({
        store_id: draft.store.storeId,
        store_slug: draft.store.slug,
        target_date: draft.dateYmd,
        facts_id: draft.factsId,
        mdx_content: mdx,
        insight_json: insightPayload as unknown as Record<string, unknown>,
        source: "line_webhook",
        line_user_id: lineUserId,
        error_message: null,
      });
      if (ins.ok) {
        dbNote = `\n保存ID: ${ins.id}`;
      } else {
        dbNote = `\n※DB保存スキップ: ${ins.error}`;
      }
    } else {
      dbNote = "\n※Supabase未設定のためDBには保存していません（GEMINIのみ生成）。";
    }

    const summary = [
      `下書きを生成しました（${draft.store.label} / ${draft.dateYmd}）`,
      `facts_id: ${draft.factsId}`,
      `混雑: ${insightResult.insight.crowd_label || "—"} / ピーク ${insightResult.insight.peak_time || "—"} / 避けたい ${insightResult.insight.avoid_time || "—"}`,
      `データ: ${insightResult.source} shift=${insightResult.shift}`,
      dbNote,
      "",
      "---- MDX（冒頭）----",
      truncate(mdx, 3500),
    ].join("\n");

    await replyLine(replyToken, summary);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[line] processMessageEvent", msg);

    if (isBlogDraftsConfigured()) {
      await insertBlogDraft({
        store_id: draft.store.storeId,
        store_slug: draft.store.slug,
        target_date: draft.dateYmd,
        facts_id: draft.factsId,
        mdx_content: "",
        insight_json: {},
        source: "line_webhook",
        line_user_id: lineUserId,
        error_message: msg,
      });
    }

    await replyLine(replyToken, `処理中にエラーが発生しました。\n${truncate(msg, 800)}`);
  }
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
  const forceSkip = process.env.SKIP_LINE_SIGNATURE_VERIFY === "1";
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

  // Vercel serverless 上で `after()` がサスペンドされ、返信処理まで完遂されないケースがあるため、
  // ここでは webhook 完了まで同期的に待つ（LINE には 200 を返す）。
  try {
    await handleWebhookBody(rawBody);
  } catch (err) {
    console.error("[line] POST handleWebhookBody failed", err);
  }

  return new NextResponse("OK", { status: 200 });
}
