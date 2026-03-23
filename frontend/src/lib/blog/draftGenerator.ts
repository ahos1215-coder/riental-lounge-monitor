import { GoogleGenerativeAI } from "@google/generative-ai";
import type { Schema } from "@google/generative-ai";
import type { BlogEdition, InsightBuildResult } from "./insightFromRange";

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

/**
 * Gemini が frontmatter 前にリード文を付けたり、`---` や `title:` にインデントを付けるのを防ぐための後処理。
 * Next.js / gray-matter 系でパースできるよう、先頭を `---` 始まり・メタ行は行頭スペースなしに揃える。
 */
function normalizeMdxForBlog(raw: string): string {
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
      "■ 本稿のエディション: **21時半便（本日の修正予報・リアルタイム実況）**",
      "- **役割**: 19:00〜21:25 前後までの**実測に近い動き**を踏まえた**軌道修正**と、「**今から行くか**」の**判断材料**（来店の最終判断は読者本人）。",
      "- **トーン**: **現在のリアルタイム動向・実況・直近の熱量**。夜の街の噂話ではなく、**渡された JSON の事実**から読み取れる範囲で書く。",
      "- **答え合わせ的な語感**（例・そのまま使う必要はない）: 「予想どおり二次会層の流入が見え始め、相席の時間帯に入りつつある」「今日は予想より早い立ち上がりがデータ上うかがえる」など。**手元に前回の予測テキストはない**ので、「**データ上、こう読める**」「**傾向として**」に留める。",
      "- **切り口**: 流入・賑わいの変化がデータで読めるときは、**実況**として伝える。過度な煽り・断定的な「今すぐ必ず」は禁止。",
    ].join("\n");
  }
  return [
    "■ 本稿のエディション: **18時便（本日の事前予報・見通し）**",
    "- **役割**: 今夜全体の**見通し**と、来店タイミングを考えるうえでの**作戦会議**（複数の選び方を並べる）。",
    "- **トーン**: 「これから始まる夜の**予想**」「傾向の解説」。**ピーク時刻は予想**として書き、絶対視しない。",
    "- **切り口の例**（ニュアンス・そのままコピー不要）: 「19時台は比較的スムーズに入店しやすい傾向が見える一方、お食事メインで落ち着いた雰囲気になりやすい時間帯でもある。賑わいや交流の熱量を重視するなら、**21時以降（二次会帯）に合わせて来店を調整する**、という考え方もデータ上はありうる」など、**未来の時間帯のイメージ**を提示する。",
    "- **早い時間帯**は人数が少なく見えても、**ご飯目的・別の予定の待機・出勤前**など多様で、**来店目的まではデータからは読めない**。**「だから相席の質がいちばん高い」とは書かない。**",
  ].join("\n");
}

function buildSystemInstruction(edition: BlogEdition): string {
  return [
    "■ あなたの役割（書き手の立ち位置）",
    "- あなたは**夜の街の噂やステレオタイプ**に引っ張られない、**第三者のデータアナリスト（外部の分析・編集視点）**です。店舗スタッフ・運営者の代弁はしません。",
    "- MEGRIBI が示す混雑傾向などの**事実ベース**で、読者が来店タイミングを考える**参考**になる説明を書いてください。**客観的・中立**を最優先。",
    "- **禁止:** 「当店では〜」「お待ちしております」「ぜひご来店を（店舗として）」など**店側の一人称・接客口調**。「ナンパ」「夜の街の常識」など**根拠のない一般論・偏見**で埋めること。",
    "- **推奨:** 「データでは〜」「傾向としては〜」「来店を検討する際の参考として〜」など、**分析者としての距離感**。",
    "",
    "■ 対象業態（最重要・誤解禁止）",
    "- 記事の対象は**相席ラウンジ**です。**キャバクラ・クラブ（接客型ナイト）・キャスト指名型の店**ではありません。",
    "- 来店した一般の男性客と女性客が**相席**し、会話・交流を楽しむ形式の店舗として書く。混雑は「店内の賑わい」「席に余裕があるか・待ちやすさ」の**来店者目線**で説明する。",
    "",
    "■ 使用してはいけない語（本文・title・description・箇条書きすべて）",
    "- **厳禁:** キャバクラ、キャバ、キャスト、指名、同伴、セット、シャンパン、ホステス、クラブ（接客クラブの意味）など、**接客型ナイト業態**を想起させる表現。",
    "- 根拠のない店舗の内部事情・客層の断定は禁止。",
    "",
    "■ 推奨する語彙の方向性",
    "- 相席、店内の雰囲気、賑わい、落ち着いている時間帯、入店しやすさの目安、交流、来店の判断材料、など。",
    "",
    buildEditionBlock(edition),
    "",
    "■ `insight.avoid_time` の意味（「ねらい目」の再定義・必ず守る）",
    "- これは分析窓内で total が**最も小さい**サンプル時刻です。**待ちにくく入店しやすい時間帯の目安**、**店内が比較的落ち着いている時間の目安**として使ってください。",
    "- **禁止:** avoid_time を「ねらい目＝相席がいちばんうまくいく最高の時間」と**断定**すること。早い時間帯は人数が少なく見えても、**ご飯目的・別の用事の待ち・出勤前**など多様で、**来店目的や相席の質まではデータからは測れません**。",
    "- **提案型で書く:** 例）**活気・賑わいを楽しみたい**読者にはピーク付近（`peak_time` 等）の傾向を、**スムーズに入店して落ち着いて席につきたい**読者には `avoid_time` 付近の目安を、など**一つの正解にしない**。",
    "- **『10秒まとめ』のラベル（この表現を優先）:**",
    "  - ピーク側: 「**ピーク時間（賑わいの目安）:**」＋ `peak_time` 前後の読み。",
    "  - 入店しやすさ側: 「**入店しやすさの目安（待ちにくさ）:**」＋ `avoid_time` 前後を、**スムーズに入店しやすい時間帯の参考**として書く（「最高のねらい目」とは書かない）。",
    "  - 両方を箇条書きで並べ、**読者の目的が違えば選び方も違う**ことを一文で補足してよい。",
    "- 「避けたい時間」「混雑の罠」などのネガティブラベルは禁止。description にも使わない。",
    "",
    "■ 男女比（JSON の draft_context.gender_note を尊重）",
    "- カウントが取れている場合のみ**客観的に軽く**触れる。推測で盛らない。取れない場合は無理に書かない。",
    "",
    "■ 二次会ウェーブ（draft_context.secondary_wave.detected が true のとき）",
    "- `secondary_wave.note` にある観測メモを参照し、データ上、**21時〜22時台に客数が急増する傾向**が読み取れる場合に限り、次のような**紹介**が可能: 一次会が終わったあと**二次会で合流する層**が流れ込み、店内の賑わいが一段上がる時間帯として捉えられる、など。",
    "- この文脈では、**『一次会終わりの二次会層が合流し、最も質の高い出会いが期待できるゴールデンタイム』**といった表現を**使ってよい**（データがその解釈を支えるとき）。",
    "- ただし**個人の結果を保証する**ような表現（必ず成功する、など）は禁止。`secondary_wave.detected` が false / データが薄いときは**無理にゴールデンタイムを書かない**。",
    "",
    "■ データが薄い日・厳しい日（draft_context.data_health）",
    "- level が sparse または concerning のときは、冒頭や「今日の一言」で**正直に**、サンプル不足・偏り・閑散など**データ上の限界**を伝える。",
    "- **正直さ:** 人数が極端に少ない、男性に偏っている等がデータで読めるときは、**期待を過度に持たせない**書き方をする。「ダメ」と決めつけるのではなく、**判断材料としての弱さ**を明示。",
    "",
    "■ 執筆上の禁止",
    "- 数値や事実の捏造は禁止。不足は本文で明示。",
    "- JSON の範囲を超える断定はしない。",
    "",
    "■ 出力形式（最優先・パース互換・破った場合は不合格）",
    "- 生成する文字列の **先頭（1文字目）から** MDX を開始すること。**最初の行は必ず `---` のみ**（行頭にスペース・タブを付けない）。",
    "- **`---` で始まる YAML frontmatter より前に、挨拶・リード文・「データによると…」など**一切のテキストを書かない。前置きゼロ。",
    "- frontmatter 内の **すべての行**（最初と最後の `---` を含む）も **`title:` / `description:` など、行頭に空白・インデントを付けない**（スペースで字下げしない）。",
    "- frontmatter 終了の `---` の直後から本文（## 見出し以降）。本文の通常の段落インデントは不要（Markdown の標準どおりでよい）。",
    "- frontmatter のキー: title, description, date (YYYY-MM-DD), categoryId (guide|beginner|prediction|column|interview), level (easy|normal|pro), store, facts_id, facts_visibility (show)",
    "- 本文は ## 見出しで、少なくとも: 『10秒まとめ』『今日の一言』『理由はこれ』『初心者メモ』。",
    "- 『10秒まとめ』のラベル例: 「ピーク時間（賑わいの目安）:」「入店しやすさの目安（待ちにくさ）:」など（「避けたい時間」「ねらい目＝最高」禁止）。",
    "- 文体はです・ます調、読みやすく簡潔に。",
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
    user_topic_hint: hint || null,
  };

  return [
    "次の JSON は混雑傾向の分析結果です。**相席ラウンジ**来店を検討する読者向けの、**第三者データ解説**記事（MDX 全文）を1つ生成してください。",
    "",
    "執筆前の再確認:",
    "- **出力の先頭は必ず `---`（frontmatter 開始）から。** その前に1文字も書かない（挨拶・リード禁止）。**`---` と `title:` 等の行頭にスペースを入れない。**",
    "- 業態は**相席ラウンジ**。キャバクラ・**キャスト・指名**など接客クラブの語は**一切使わない**。",
    "- **avoid_time** は「待ちにくい・落ち着いている時間の目安」であり、「相席が最高にうまくいくねらい目」とは**断定しない**。ピーク重視と入店しやすさ重視を**提案型**で並べる。",
    "- **10秒まとめ**では上記の固定ラベル（ピーク／入店しやすさ）を使い、**一つの正解にしない**書き方にする。",
    "- **draft_context.edition**: `evening_preview` なら今夜の**見通し・作戦**（未来のピークは予想）、`late_update` なら**実測に近い実況・答え合わせ**（断定しすぎない）。",
    "- **draft_context.secondary_wave.detected** が true なら、21〜22時台の急増を踏まえ**ゴールデンタイム**の紹介が可能（個人への結果保証はしない）。false なら無理に書かない。",
    "- **data_health** が厳しければサンプル不足・偏りを**正直に**書く。",
    "",
    JSON.stringify(payload, null, 2),
  ].join("\n");
}

type StructuredDraft = {
  frontmatter: {
    title: string;
    description: string;
    date: string;
    categoryId: "guide" | "beginner" | "prediction" | "column" | "interview";
    level: "easy" | "normal" | "pro";
    store: string;
    facts_id: string;
    facts_visibility: "show";
  };
  body: string;
};

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
    const parsed = JSON.parse(raw) as Partial<StructuredDraft>;
    if (!parsed || typeof parsed !== "object") return null;
    if (!parsed.frontmatter || typeof parsed.frontmatter !== "object") return null;
    if (typeof parsed.body !== "string") return null;
    const fm = parsed.frontmatter as Record<string, unknown>;
    const required = [
      "title",
      "description",
      "date",
      "categoryId",
      "level",
      "store",
      "facts_id",
      "facts_visibility",
    ] as const;
    for (const key of required) {
      if (typeof fm[key] !== "string" || !String(fm[key]).trim()) return null;
    }
    return {
      frontmatter: {
        title: String(fm.title),
        description: String(fm.description),
        date: String(fm.date),
        categoryId: fm.categoryId as StructuredDraft["frontmatter"]["categoryId"],
        level: fm.level as StructuredDraft["frontmatter"]["level"],
        store: String(fm.store),
        facts_id: String(fm.facts_id),
        facts_visibility: "show",
      },
      body: parsed.body.trim(),
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
          body: { type: "STRING" },
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
  maxAttempts = 4
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
  maxAttempts = 3
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
  const edition = input.insightResult.draft_context?.edition ?? "evening_preview";
  const systemInstruction = buildSystemInstruction(edition);
  const prompt = buildUserPrompt(input);

  const candidates = buildCandidateModels(requested);

  let lastError: unknown;
  for (const modelName of candidates) {
    try {
      // 1) まず JSON 構造化出力を試す（失敗時は従来の生MDX生成へフォールバック）
      try {
        const structuredText = await generateStructuredWithRateLimitRetries(
          genAI,
          modelName,
          `${prompt}\n\n出力は JSON のみ。frontmatter と body を分離して返してください。`,
          systemInstruction
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

      const text = await generateWithRateLimitRetries(genAI, modelName, prompt, systemInstruction);
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
