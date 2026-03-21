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

const DEFAULT_MODEL = "gemini-2.0-flash";

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

/**
 * Generate MDX draft using Gemini. Requires GEMINI_API_KEY.
 */
export async function generateBlogDraftMdx(input: DraftGeneratorInput): Promise<string> {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not set");
  }

  const modelId = process.env.GEMINI_MODEL?.trim() || DEFAULT_MODEL;
  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({
    model: modelId,
    systemInstruction: buildSystemInstruction(),
  });

  const result = await model.generateContent(buildUserPrompt(input));
  const text = result.response.text();
  if (!text?.trim()) {
    throw new Error("Gemini returned empty content");
  }

  // Strip optional markdown code fence
  let mdx = text.trim();
  if (mdx.startsWith("```")) {
    mdx = mdx.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n```\s*$/, "");
  }
  return mdx.trim();
}
