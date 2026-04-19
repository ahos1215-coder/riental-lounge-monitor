import { GoogleGenerativeAI } from "@google/generative-ai";
import type { Schema } from "@google/generative-ai";
import { z } from "zod";
import type { BlogEdition, InsightBuildResult } from "./insightFromRange";

export type DraftGeneratorInput = {
  storeLabel: string;
  storeSlug: string;
  dateYmd: string;
  factsId: string;
  insightResult: InsightBuildResult;
  /** Extra instructions from LINE (topic, tone, audience) */
  topicHint?: string;
  /** パイプライン呼び出し元（定時 cron は rate-limit 待ちを短くする） */
  source?: "line_webhook" | "vercel_cron" | "github_actions_cron" | "github_actions_retry" | "manual_api";
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

function maxRateLimitWaitSeconds(source?: DraftGeneratorInput["source"]): number {
  // 定時 cron は 1店舗=1リクエストでも、GHA の並列実行で 429 待ちが発生しやすい。
  // ここで長時間 sleep すると Vercel の実行上限(60s)に達し、mdx が空で保存されてしまうため、
  // cron 系は短い待ちで諦めて呼び出し元でフォールバック生成する。
  if (source === "github_actions_cron" || source === "github_actions_retry" || source === "vercel_cron") {
    return 3;
  }
  return 120;
}

/**
 * Gemini が frontmatter 前にリード文を付けたり、`---` や `title:` にインデントを付けるのを防ぐための後処理。
 * Next.js / gray-matter 系でパースできるよう、先頭を `---` 始まり・メタ行は行頭スペースなしに揃える。
 */
export function normalizeMdxForBlog(raw: string): string {
  let s = raw.replace(/^\uFEFF/, "").trim();
  if (s.startsWith("```")) {
    s = s.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n```\s*$/, "");
  }
  const lines = s.split(/\r?\n/);
  const startIdx = lines.findIndex((l) => l.trim() === "---");
  if (startIdx < 0) {
    return s.trim();
  }

  const rest = lines.slice(startIdx);
  rest[0] = "---";

  let endFm = -1;
  for (let i = 1; i < rest.length; i++) {
    if (rest[i].trim() === "---") {
      endFm = i;
      break;
    }
  }

  if (endFm < 0) {
    return rest.map((line, i) => (i === 0 ? "---" : line.trimStart())).join("\n").trim();
  }

  rest[endFm] = "---";
  for (let i = 1; i < endFm; i++) {
    rest[i] = rest[i].trimStart();
  }

  const bodyLines = rest.slice(endFm + 1);
  while (bodyLines.length > 0 && bodyLines[0].trim() === "") {
    bodyLines.shift();
  }

  return [...rest.slice(0, endFm + 1), ...bodyLines].join("\n").trim();
}

function buildEditionBlock(edition: BlogEdition): string {
  if (edition === "late_update") {
    return [
      "■ このエディション: 21時半便 (今の観察)",
      "- いま、この瞬間の店内の空気感をデータから読み取り、残り時間（2〜3時間）で何が起きそうかを伝える。",
      "- 現在形・完了形中心:「〜来た」「〜抜けた」「〜遅れている」「〜の気配」。",
      "- 読み手は既に飲んでいる人、もしくは今から出ようとしている人。「残り時間をどう動くか」がフック。",
      "- 重要: 18時便の予測には一切言及しない。「予想どおり」「予想を外れて」などの答え合わせ語は使わない。純粋に「今、こうなっている」の観察として書く。",
    ].join("\n");
  }
  return [
    "■ このエディション: 18時便 (今夜の見通し)",
    "- 今夜これから起きる波の形を時系列で予告する。予測なので断定しない。",
    "- 未来形・推量形中心:「〜になりそう」「〜の気配」「〜かもしれない」。",
    "- 読み手はこれから出かける人。「今夜いつ動くか」がフック。",
    "- 先週比・曜日比が効くのはこのエディション。いつもと違う要素があれば、そこを入り口に書き出す。",
  ].join("\n");
}

function buildSystemInstruction(edition: BlogEdition): string {
  return [
    "■ あなたの役割",
    "あなたは MEGRIBI の観測者。相席ラウンジの混雑データを毎日眺めてきた人で、数字の奥にある夜の流れを読む。店のスタッフでも営業マンでもない。データを見ながら友人にぽつりとつぶやく、そういう距離感で書く。",
    "",
    "■ 視点",
    "データが示すのは「人の流れ」で、店の良し悪しではない。混雑が意味を持つのは、読み手が今夜その店に行くかどうか判断する材料になるときだけ。だから「何時にどう変わるか」を時間の流れで見せる。スナップショットではなく、波として書く。",
    "",
    "■ トーン",
    "夜遊びに詳しい友人がスマホでデータを眺めながら口にするくらいの温度。断定と過剰演出をしない。「〜らしい」「〜っぽい」「〜の気配」「〜そう」「〜かもしれない」のような観測者の距離を保つ。",
    "",
    "■ 業態（誤解禁止）",
    "対象は相席ラウンジ。一般男女が相席して会話・交流を楽しむ店。キャバクラ・クラブ（接客型）ではない。混雑は「店内の賑わい」「席の待ちやすさ」の来店者目線で語る。",
    "",
    "■ 使ってはいけない語",
    "キャバクラ、キャバ、キャスト、指名、同伴、セット、シャンパン、ホステス、クラブ（接客クラブの意味）。営業的な「ぜひお越しください」「お待ちしております」系の文句。",
    "",
    "■ 書くもの",
    "- 今夜（または今）の波の形: いつ盛り上がっていつ落ちるか",
    "- 普段と違う要素があれば、どう違うか（先週比・曜日・天気など）",
    "- 読み手が「で、いつ行けばいいのか」を判断できる材料",
    "",
    "■ 書かないもの",
    "- 開店直後の閑散（avoid_time は記事に書かない。食事目的層があり相席の質とは無関係なため）",
    "- 店や客層の良し悪しの評価",
    "- 挨拶、リード文、自己紹介",
    "- 箇条書き（「- 」や「・」で始まる行を使わない。全文を自然文で書く）",
    "- 見出し（## などの Markdown 見出しは使わない。本文は見出しなしで直接書き始める）",
    "",
    "■ 予測は断定しない（重要）",
    "予測は外れる。外れたときに記事の信頼を損なわないよう、ピーク時間も二次ピークも「〜あたりが山になりそう」「〜の気配」の書き方にする。",
    "❌ 「21時にピークが来ます」",
    "✅ 「21時あたりが山になりそう」",
    "❌ 「22:30に第2波が来ます」",
    "✅ 「22時半あたりから二次ピークの気配」",
    "",
    buildEditionBlock(edition),
    "",
    "■ データの扱い",
    "- peak_time と crowd_label は記事の軸。avoid_time は使わない。",
    "- 男女比（draft_context.gender_note）: カウントが取れているときのみ客観的に軽く触れる。推測で盛らない。",
    "- 曜日コンテキスト（draft_context.day_context）: 曜日に合った文脈を1文添えてよい（データと矛盾しない範囲で）。",
    "- 先週同曜日比較（draft_context.week_comparison）: available のときだけ trend_note を1文で触れてよい。unavailable なら触れない。",
    "- 二次ピーク（draft_context.secondary_wave）: detected=true のときだけ触れる。false なら無理にゴールデンタイムを書かない。",
    "- データ健全性（draft_context.data_health）: sparse/concerning のときは、サンプル不足・偏りを正直に書く。期待を過度に持たせない。",
    "",
    "■ 構造と文量",
    "毎回違う入り方をする。データの中で一番目立つ要素から書き出す:",
    "「今夜は〜」「21時台が〜」「先週より〜」「金曜の割に〜」「二次ピークが〜」など。",
    "本文は 100〜200字が目安。無理に延ばさない。2〜3文で収まるなら短くてよい。",
    "",
    "■ 出力（JSON 構造化）",
    "- frontmatter.title: 店名 + 結論の短い一行（例「渋谷 今夜は二次ピーク強め」）、50字以内。",
    "- frontmatter.description: 結論の要約（100字以内）。「ピーク21時前後」のような事実ベースで。",
    "- frontmatter.date: YYYY-MM-DD。",
    "- frontmatter.categoryId: \"prediction\"。",
    "- frontmatter.level: \"easy\"。",
    "- frontmatter.store: JSON の store_slug。",
    "- frontmatter.facts_id: JSON の facts_id。",
    "- frontmatter.facts_visibility: \"show\"。",
    "- body: 自然文 100〜200字。見出しなし、箇条書きなし。先頭から本文。",
    "",
    "■ 良い例（目指すトーン）",
    "evening_preview の例: 「渋谷の金曜にしては一次ピークが控えめで、21時に一山来たあと22時前に一度落ち着きそう。そのあと22時半あたりから終電前の戻りが来る気配があって、今夜はむしろこの二番目の波のほうがはっきり出るかもしれない。先週金曜はここが平坦だったので、今週は空気が違う。」",
    "late_update の例: 「22時の時点で21時の一山はもう抜けきって、店内は小康状態。終電前の戻りはまだ立ち上がっていない印象で、このまま落ち着くか二次ピークが来るか読みにくいところ。小雨が効いているのかもしれない。」",
    "",
    "■ 避ける例（やらない）",
    "- 箇条書き「- 混雑度: やや混雑 / - ピーク時間: 21:00」: データを並べただけで観察がない。",
    "- 断定口調「必ず21時にピークが来ます」: 外れたときに信頼を損なう。",
    "- 営業文句「ぜひお越しください」: 店側の代弁になる。",
    "- 見出し挿入「## 今日の結論」: 本文は見出しなしで書く。",
  ].join("\n");
}

function buildUserPrompt(input: DraftGeneratorInput): string {
  const { insight, range, quality_flags, source, shift, draft_context } = input.insightResult;
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
    draft_context,
    hourly_hint_excerpt: draft_context.hourly_hint,
    day_context: draft_context.day_context ?? null,
    week_comparison: draft_context.week_comparison ?? null,
    user_topic_hint: hint || null,
  };

  return [
    "次の JSON データをもとに、相席ラウンジ来店を検討する読者向けの短い観測記事を書いてください。",
    "",
    "出力形式（JSON 構造化）:",
    "- frontmatter.title: 店名 + 結論の短い一行（50字以内）",
    "- frontmatter.description: 結論の要約（100字以内）",
    "- frontmatter.date: JSON の date をそのまま",
    "- frontmatter.categoryId: \"prediction\"",
    "- frontmatter.level: \"easy\"",
    "- frontmatter.store: JSON の store_slug",
    "- frontmatter.facts_id: JSON の facts_id",
    "- frontmatter.facts_visibility: \"show\"",
    "- body: 自然文 100〜200字。見出しなし、箇条書きなし。",
    "",
    "JSON データ:",
    JSON.stringify(payload, null, 2),
  ].join("\n");
}

const structuredDraftSchema = z.object({
  frontmatter: z.object({
    title: z.string().min(1).max(500),
    description: z.string().min(1).max(600),
    date: z.string().regex(/^\d{4}-\d{2}-\d{2}/, "date must start with YYYY-MM-DD"),
    categoryId: z.enum(["guide", "beginner", "prediction", "column", "interview"]),
    level: z.enum(["easy", "normal", "pro"]),
    store: z.string().min(1).max(120),
    facts_id: z.string().min(1).max(200),
    facts_visibility: z.literal("show"),
  }),
  /** 短すぎる本文は frontmatter だけの壊れた出力とみなし却下 */
  body: z.string().min(40),
});

type StructuredDraft = z.infer<typeof structuredDraftSchema>;

function toYamlScalar(v: string): string {
  return JSON.stringify(String(v ?? ""));
}

function toMdxFromStructuredDraft(draft: StructuredDraft): string {
  const fm = draft.frontmatter;
  const body = (draft.body ?? "").trim();
  return [
    "---",
    `title: ${toYamlScalar(fm.title)}`,
    `description: ${toYamlScalar(fm.description)}`,
    `date: ${toYamlScalar(fm.date)}`,
    `categoryId: ${toYamlScalar(fm.categoryId)}`,
    `level: ${toYamlScalar(fm.level)}`,
    `store: ${toYamlScalar(fm.store)}`,
    `facts_id: ${toYamlScalar(fm.facts_id)}`,
    `facts_visibility: ${toYamlScalar(fm.facts_visibility)}`,
    "---",
    "",
    body,
  ].join("\n");
}

function parseStructuredDraft(raw: string): StructuredDraft | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    const r = structuredDraftSchema.safeParse(parsed);
    if (!r.success) return null;
    return {
      frontmatter: {
        ...r.data.frontmatter,
        facts_visibility: "show",
      },
      body: r.data.body.trim(),
    };
  } catch {
    return null;
  }
}

async function generateContentOnce(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string,
  systemInstruction: string
): Promise<string> {
  const model = genAI.getGenerativeModel({
    model: modelName,
    systemInstruction,
  });
  const result = await model.generateContent(prompt);
  return result.response.text();
}

async function generateStructuredContentOnce(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string,
  systemInstruction: string
): Promise<string> {
  const model = genAI.getGenerativeModel({
    model: modelName,
    systemInstruction,
  });
  const result = await model.generateContent({
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: ({
        type: "OBJECT",
        properties: {
          frontmatter: {
            type: "OBJECT",
            properties: {
              title: { type: "STRING" },
              description: { type: "STRING" },
              date: { type: "STRING" },
              categoryId: { type: "STRING", enum: ["guide", "beginner", "prediction", "column", "interview"] },
              level: { type: "STRING", enum: ["easy", "normal", "pro"] },
              store: { type: "STRING" },
              facts_id: { type: "STRING" },
              facts_visibility: { type: "STRING", enum: ["show"] },
            },
            required: [
              "title",
              "description",
              "date",
              "categoryId",
              "level",
              "store",
              "facts_id",
              "facts_visibility",
            ],
          },
          body: {
            type: "STRING",
            description: "自然文 100〜200字。見出しなし、箇条書きなし。frontmatter は含めない。",
          },
        },
        required: ["frontmatter", "body"],
      } as unknown as Schema),
    },
  });
  return result.response.text();
}

/**
 * 429 は短時間のクォータ超過で起きることが多い。指数バックオフ + API が示す待ち秒。
 */
async function generateWithRateLimitRetries(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string,
  systemInstruction: string,
  maxAttempts = 4,
  maxWaitSec = 120
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const text = await generateContentOnce(genAI, modelName, prompt, systemInstruction);
      if (text?.trim()) return text;
      throw new Error("Gemini returned empty content");
    } catch (e) {
      lastErr = e;
      if (!isRateLimitError(e) || attempt >= maxAttempts - 1) {
        throw e;
      }
      const fromApi = parseRetryAfterSeconds(e);
      const backoffSec = fromApi ?? Math.min(90, 15 * 2 ** attempt);
      if (backoffSec > maxWaitSec) {
        throw new Error(`rate limited (retry-after ${backoffSec}s)`);
      }
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

async function generateStructuredWithRateLimitRetries(
  genAI: GoogleGenerativeAI,
  modelName: string,
  prompt: string,
  systemInstruction: string,
  maxAttempts = 3,
  maxWaitSec = 120
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const text = await generateStructuredContentOnce(genAI, modelName, prompt, systemInstruction);
      if (text?.trim()) return text;
      throw new Error("Gemini structured response was empty");
    } catch (e) {
      lastErr = e;
      if (!isRateLimitError(e) || attempt >= maxAttempts - 1) {
        throw e;
      }
      const fromApi = parseRetryAfterSeconds(e);
      const backoffSec = fromApi ?? Math.min(60, 10 * 2 ** attempt);
      if (backoffSec > maxWaitSec) {
        throw new Error(`rate limited (retry-after ${backoffSec}s)`);
      }
      await sleep(backoffSec * 1000);
    }
  }
  throw lastErr;
}

export function buildFallbackBlogDraftMdx(input: DraftGeneratorInput): string {
  const { insight, draft_context } = input.insightResult;
  const title = `${input.storeLabel}｜今日の傾向まとめ（${input.dateYmd}）`;
  const peak = insight.peak_time || "—";
  const crowd = insight.crowd_label || "—";
  const dayLabel = draft_context?.day_context?.day_name_ja ?? "";
  const wave = draft_context?.secondary_wave?.detected
    ? `二次会帯（21〜22時頃）に人が増える傾向${draft_context.secondary_wave.note ? `（${draft_context.secondary_wave.note}）` : ""}`
    : null;

  const bullets: string[] = [
    `混雑度（目安）: ${crowd}${dayLabel ? `（${dayLabel}）` : ""}`,
    `ピーク時間: ${peak} 前後 — この時間以降、人が減り始める傾向です`,
  ];
  if (wave) {
    bullets.push(wave);
  }

  return [
    "---",
    `title: "${title}"`,
    `description: "${input.storeLabel}の今夜の混雑予測。ピーク${peak}前後。"`,
    `date: "${input.dateYmd}"`,
    "categoryId: prediction",
    "level: easy",
    `store: "${input.storeSlug}"`,
    `facts_id: "${input.factsId}"`,
    "facts_visibility: show",
    "---",
    "",
    "## 今日の結論",
    ...bullets.map((b) => `- ${b}`),
    "",
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

  const requested = resolveGeminiModel(process.env.GEMINI_MODEL);
  const genAI = new GoogleGenerativeAI(apiKey);
  const edition = input.insightResult.draft_context?.edition ?? "evening_preview";
  const systemInstruction = buildSystemInstruction(edition);
  const prompt = buildUserPrompt(input);

  const candidates = buildCandidateModels(requested);
  const maxWaitSec = maxRateLimitWaitSeconds(input.source);

  let lastError: unknown;
  for (const modelName of candidates) {
    try {
      // 1) まず JSON 構造化出力を試す（失敗時は従来の生MDX生成へフォールバック）
      try {
        const structuredText = await generateStructuredWithRateLimitRetries(
          genAI,
          modelName,
          `${prompt}\n\n出力は JSON のみ。frontmatter と body を分離して返してください。`,
          systemInstruction,
          3,
          maxWaitSec
        );
        const parsed = parseStructuredDraft(structuredText);
        if (parsed) {
          return normalizeMdxForBlog(toMdxFromStructuredDraft(parsed));
        }
      } catch (structuredErr) {
        console.warn("[gemini] structured output failed, fallback to mdx text", {
          model: modelName,
          error: errorMessage(structuredErr),
        });
      }

      const text = await generateWithRateLimitRetries(genAI, modelName, prompt, systemInstruction, 4, maxWaitSec);
      if (!text?.trim()) {
        throw new Error("Gemini returned empty content");
      }
      let mdx = text.trim();
      if (mdx.startsWith("```")) {
        mdx = mdx.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n```\s*$/, "");
      }
      mdx = normalizeMdxForBlog(mdx);
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
