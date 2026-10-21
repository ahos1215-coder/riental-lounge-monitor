import { describe, expect, it } from "vitest";
import { isAllowedLineSender, parseAllowedLineUserIds } from "./allowedSenders";

const OWNER = "U0123456789abcdef0123456789abcdef";
const STRANGER = "Ufedcba9876543210fedcba9876543210";

describe("parseAllowedLineUserIds", () => {
  it("LINE_ALLOWED_USER_IDS（カンマ区切り）と LINE_USER_ID を合わせ、空白と空要素を捨てる", () => {
    const ids = parseAllowedLineUserIds({
      LINE_ALLOWED_USER_IDS: ` ${OWNER} ,, Uaaa `,
      LINE_USER_ID: "Ubbb",
    });
    expect([...ids].sort()).toEqual([OWNER, "Uaaa", "Ubbb"].sort());
  });

  it("どちらも未設定なら空", () => {
    expect(parseAllowedLineUserIds({}).size).toBe(0);
  });
});

describe("isAllowedLineSender", () => {
  it("許可リストにある userId だけを通す", () => {
    const env = { NODE_ENV: "production", LINE_ALLOWED_USER_IDS: OWNER };
    expect(isAllowedLineSender(OWNER, env)).toBe(true);
    expect(isAllowedLineSender(STRANGER, env)).toBe(false);
    expect(isAllowedLineSender(null, env)).toBe(false);
    expect(isAllowedLineSender(undefined, env)).toBe(false);
  });

  it("通知用の LINE_USER_ID だけ入っていればオーナーを通す", () => {
    const env = { NODE_ENV: "production", LINE_USER_ID: OWNER };
    expect(isAllowedLineSender(OWNER, env)).toBe(true);
    expect(isAllowedLineSender(STRANGER, env)).toBe(false);
  });

  it("LINE_USER_ID がグループ ID でも、個人の userId は通らない", () => {
    const env = { NODE_ENV: "production", LINE_USER_ID: "C0123456789abcdef0123456789abcdef" };
    expect(isAllowedLineSender(STRANGER, env)).toBe(false);
  });

  it("本番で許可リストが空なら誰も通さない（fail-closed）", () => {
    expect(isAllowedLineSender(OWNER, { NODE_ENV: "production" })).toBe(false);
    expect(isAllowedLineSender(OWNER, { NODE_ENV: "test" })).toBe(false);
  });

  it("development で許可リストが空のときだけ全員通す（ローカル検証用）", () => {
    expect(isAllowedLineSender(STRANGER, { NODE_ENV: "development" })).toBe(true);
    expect(isAllowedLineSender(null, { NODE_ENV: "development" })).toBe(true);
  });

  it("development でも許可リストがあればそれに従う", () => {
    const env = { NODE_ENV: "development", LINE_ALLOWED_USER_IDS: OWNER };
    expect(isAllowedLineSender(STRANGER, env)).toBe(false);
  });
});
