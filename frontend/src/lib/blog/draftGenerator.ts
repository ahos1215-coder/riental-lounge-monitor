import { GoogleGenerativeAI } from "@google/generative-ai";
import type { InsightBuildResult } from "./insightFromRange";

export type DraftGeneratorInput = {
  storeLabel: string;
  storeSlug: string;
  dateYmd: string;
  factsId: string;
  insightResult: InsightBuildResult;
  /** Extra instructions from LINE (topic, tone, audience) */
  topicHint?: string;
};

/**
 * 現行の安定版（公式: Model code `gemini-2.5-flash`）。
 * @see https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash
 * gemini-2.0-flash は同一ドキュメント上「Deprecated」扱いのため、既定は 2.5 系へ寄せる。
 */
const DEFAULT_MODEL = "gemini-2.5-flash";

/** 404 時の第2候補（最もコスト効率が良い Flash-Lite） */
const FALLBACK_MODEL_LITE = "gemini-2.5-flash-lite";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolveGeminiModel(raw?: string): string {
  const model = raw?.trim();
  if (!model) return DEFAULT_MODEL;
  // 旧名・非推奨モデルは現行デフォルトへ寄せる（Vercel の古い GEMINI_MODEL 対策）
  const legacy = new Set([
    "gemini-1.0-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
  ]);
  if (legacy.has(model)) return DEFAULT_MODEL;
  return model;
}

function buildCandidateModels(resolved: string): string[] {
  const out: string[] = [];
  const push = (m: string) => {
    if (!out.includes(m)) out.push(m);
  };
  push(resolved);
  push(DEFAULT_MODEL);
  push(FALLBACK_MODEL_LITE);
  return out;
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function isModelNotFoundError(e: unknown): boolean {
  const msg = errorMessage(e);
  return msg.includes("[404 Not Found]") && msg.includes("models/");
}

function isRateLimitError(e: unknown): boolean {
  const msg = errorMessage(e);
  return msg.includes("[429") || msg.includes("Too Many Requests") || msg.includes("RESOURCE_EXHAUSTED");
}

/** API エラー本文の "Please retry in 55s" などを拾う */
function parseRetryAfterSeconds(e: unknown): number | null {
  const msg = errorMessage(e);
  const m = /retry in ([\d.]+)\s*s/i.exec(msg);
  if (m) return Math.min(120, Math.ceil(parseFloat(m[1])) + 2);
  return null;
}

function buildSystemInstruction(): string {
  return [
    "あなたはキャバクラ・ラウンジ業界向けのブログ編集者です。",
    "与えられた集計結果（ピーク時間・避けたい時間・混雑ラベル）のみを根拠に記事を書いてください。",
    "数値や事実の捏造は禁止です。データが不足している場合はその旨を本文で明示してください。",
    "出力は必ず MDX 形式で、YAML frontmatter を先頭に含めてください。",
    "frontmatter のキー: title, description, date (YYYY-MM-DD), categoryId (guide|beginner|prediction|column|interview), level (easy|normal|pro), store, facts_id, facts_visibility (show)",
    "本文は見出しを ## で始め、『10秒まとめ』『今日の一言』『理由はこれ』『初心者メモ』のようなセクションを含めてください。",
    "文体はです・ます調、読みやすく簡潔に。",
  ].join("\n");
}

function buildUserPrompt(input: DraftGeneratorInput): string {
  const { insight, range, quality_flags, source, shift } = input.insightResult;
  const hint = input.topicHint?.trim();

  const payload = {
    store_label: input.storeLabel,
    store_slug: input.storeSlug,
    date: input.dateYmd,
    facts_id: input.factsId,
    night_window: range,
    insight,
    data_source: source,
    forecast_shift: shift,
    quality_notes: quality_flags.notes,
    user_topic_hint: hint || null,
  };

  return [
    "次の JSON は分析結果です。これに基づきブログ記事の下書き（MDX 全文）を1つ生成してください。",
    "",
    JSON.stringify(payload, null, 2),
  ].join("\n");
}

async function generateContentOnce(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string
): Promise<string> {
  const model = genAI.getGenerativeModel({
    model: modelName,
    systemInstruction: buildSystemInstruction(),
  });
  const result = await model.generateContent(prompt);
  return result.response.text();
}

/**
 * 429 は短時間のクォータ超過で起きることが多い。指数バックオフ + API が示す待ち秒。
 */
async function generateWithRateLimitRetries(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string,
  maxAttempts = 4
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const text = await generateContentOnce(genAI, modelName, prompt);
      if (text?.trim()) return text;
      throw new Error("Gemini returned empty content");
    } catch (e) {
      lastErr = e;
      if (!isRateLimitError(e) || attempt >= maxAttempts - 1) {
        throw e;
      }
      const fromApi = parseRetryAfterSeconds(e);
      const backoffSec = fromApi ?? Math.min(90, 15 * 2 ** attempt);
      console.warn("[gemini] rate limited, retrying", {
        model: modelName,
        attempt: attempt + 1,
        waitSec: backoffSec,
      });
      await sleep(backoffSec * 1000);
    }
  }
  throw lastErr;
}

/**
 * Generate MDX draft using Gemini. Requires GEMINI_API_KEY.
 */
export async function generateBlogDraftMdx(input: DraftGeneratorInput): Promise<string> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not set");
  }

  const requested = resolveGeminiModel(process.env.GEMINI_MODEL);
  const genAI = new GoogleGenerativeAI(apiKey);
  const prompt = buildUserPrompt(input);

  const candidates = buildCandidateModels(requested);

  let lastError: unknown;
  for (const modelName of candidates) {
    try {
      const text = await generateWithRateLimitRetries(genAI, modelName, prompt);
      if (!text?.trim()) {
        throw new Error("Gemini returned empty content");
      }
      let mdx = text.trim();
      if (mdx.startsWith("```")) {
        mdx = mdx.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n```\s*$/, "");
      }
      return mdx.trim();
    } catch (e) {
      lastError = e;
      if (isModelNotFoundError(e)) {
        console.warn("[gemini] model not found, trying next candidate", { model: modelName });
        continue;
      }
      throw e;
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}
