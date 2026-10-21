import crypto from "node:crypto";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 署名が正しい（＝本物の LINE 経由の）イベントでも、許可リスト外の送信者は
 * 下書き生成・公開まで進まないことを route 全体で確かめる（2026-10-22 セキュリティ点検）。
 */

const SECRET = "test-channel-secret";
const OWNER = "U0123456789abcdef0123456789abcdef";
const STRANGER = "Ufedcba9876543210fedcba9876543210";

function signedRequest(userId: string, text: string): NextRequest {
  const body = JSON.stringify({
    events: [
      {
        type: "message",
        replyToken: "reply-token",
        source: { type: "user", userId },
        message: { type: "text", text },
      },
    ],
  });
  const sig = crypto.createHmac("sha256", SECRET).update(body).digest("base64");
  return new NextRequest("https://example.test/api/line", {
    method: "POST",
    body,
    headers: { "content-type": "application/json", "x-line-signature": sig },
  });
}

describe("POST /api/line の送信者制限", () => {
  const fetchMock = vi.fn(async (..._args: [RequestInfo | URL, RequestInit?]) => new Response("{}", { status: 200 }));

  beforeEach(() => {
    vi.stubEnv("LINE_CHANNEL_SECRET", SECRET);
    vi.stubEnv("LINE_CHANNEL_ACCESS_TOKEN", "test-token");
    vi.stubEnv("LINE_ALLOWED_USER_IDS", OWNER);
    vi.stubEnv("LINE_USER_ID", "");
    vi.stubEnv("LINE_RATE_LIMIT_DISABLED", "1");
    vi.stubEnv("SUPABASE_URL", "https://supabase.test");
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "test-key");
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  function calledUrls(): string[] {
    return fetchMock.mock.calls.map(([url]) => String(url));
  }

  function replyTexts(): string[] {
    return fetchMock.mock.calls
      .filter(([url]) => String(url).includes("api.line.me"))
      .map(([, init]) => JSON.parse(String(init?.body)).messages[0].text as string);
  }

  it("許可リスト外の「公開」は Supabase に触れず、管理者専用の返信だけ返す", async () => {
    const { POST } = await import("./route");
    const res = await POST(signedRequest(STRANGER, "公開"));
    expect(res.status).toBe(200);
    expect(calledUrls().some((u) => u.includes("supabase.test"))).toBe(false);
    expect(replyTexts()).toHaveLength(1);
    expect(replyTexts()[0]).toContain("管理者専用");
    expect(replyTexts()[0]).toContain(STRANGER);
  });

  it("許可リスト外の slug 指定の公開・下書き依頼も同じく止まる", async () => {
    const { POST } = await import("./route");
    for (const text of ["shibuya-20261020 を公開", "渋谷 今夜"]) {
      fetchMock.mockClear();
      await POST(signedRequest(STRANGER, text));
      expect(calledUrls().every((u) => u.includes("api.line.me"))).toBe(true);
      expect(replyTexts()[0]).toContain("管理者専用");
    }
  });

  it("許可リストの送信者はコマンドが通る（ヘルプが返る）", async () => {
    const { POST } = await import("./route");
    await POST(signedRequest(OWNER, "ヘルプ"));
    expect(replyTexts()).toHaveLength(1);
    expect(replyTexts()[0]).not.toContain("管理者専用");
    expect(replyTexts()[0]).toContain("公開");
  });
});
