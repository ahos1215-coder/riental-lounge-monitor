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
    "■ `insight.avoid_time` について（**記事には書かない**）",
    "- JSON に `avoid_time` が含まれていますが、これは**人数が最も少ない時刻**に過ぎません。",
    "- 開店直後（19時台）は人数が少なく見えても、**食事目的・出勤前の層**など多様で、**相席の質とは無関係**です。",
    "- **記事には `avoid_time` を一切使わない**。「入店のおすすめ」「入店しやすさの目安」「ねらい目」等の表現も禁止。",
    "- 記事で伝えるのは **`peak_time`（ピーク時間）と `crowd_label`（混雑度）のみ**。",
    "",
    "■ ピーク時間の書き方",
    "- ラベル: 「**ピーク時間:**」＋ `peak_time` 前後",
    "- 意味: この時間帯が最も人が多く、以降は減り始める傾向",
    "- 「避けたい時間」「混雑の罠」などのネガティブラベルは禁止。",
    "",
    "■ 男女比（JSON の draft_context.gender_note を尊重）",
    "- カウントが取れている場合のみ**客観的に軽く**触れる。推測で盛らない。取れない場合は無理に書かない。",
    "",
    "■ 二次会ウェーブ（draft_context.secondary_wave.detected が true のとき）",
    "- `secondary_wave.note` にある観測メモを参照し、データ上、**21時〜22時台に客数が急増する傾向**が読み取れる場合に限り、次のような**紹介**が可能: 一次会が終わったあと**二次会で合流する層**が流れ込み、店内の賑わいが一段上がる時間帯として捉えられる、など。",
    "- この文脈では、**『一次会終わりの二次会層が合流し、最も質の高い出会いが期待できるゴールデンタイム』**といった表現を**使ってよい**（データがその解釈を支えるとき）。",
    "- ただし**個人の結果を保証する**ような表現（必ず成功する、など）は禁止。`secondary_wave.detected` が false / データが薄いときは**無理にゴールデンタイムを書かない**。",
    "",
    "■ 曜日コンテキストと週次比較（draft_context.day_context, draft_context.week_comparison）",
    "- `day_context.day_name_ja` を活用し、**曜日に合った文脈**を1文添えてください。",
    "  - 金曜・土曜: 「週末の夜は賑わいやすい傾向」など（データと矛盾しない範囲で）。",
    "  - 日〜木: 「平日は比較的落ち着いている傾向」など。",
    "- `week_comparison.available` が true なら、**過去の同曜日との比較**を `trend_note` をもとに1文で触れてよい。",
    "  - 例: 「過去3週の金曜平均（約65人）を上回る傾向です」",
    "- week_comparison が unavailable（データ不足）なら無理に書かない。",
    "- **注意**: 曜日言及は1〜2文で十分。長い曜日分析は不要。",
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
    "- 本文は ## 見出し 1 つ（「## 今日の結論」）のみ。箇条書き 3〜4 行。今日の一言・理由はこれ・初心者メモ・混みやすい時間 / 避けたい時間・補足メモ等の追加セクションは**すべて不要**。",
    "- 必ず含める情報（この順番で箇条書き）:",
    "  1. **混雑度**（空き / ほどよい / 混み）+ 曜日",
    "  2. **ピーク時間**: `peak_time` 前後 — 「この時間以降、人が減り始める傾向です」",
    "  3. 二次会ウェーブがある場合のみ: 21〜22時帯の傾向を 1 文",
    "- **avoid_time は書かない**（理由はシステム指示の avoid_time 節を参照）。",
    "- description も「ピーク○○前後」のように結論を入れる。",
    "- 文体はです・ます調、読みやすく簡潔に。長い説明や解説は書かない。",
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
    "次の JSON は混雑傾向の分析結果です。**相席ラウンジ**来店を検討する読者向けの、**第三者データ解説**記事（MDX 全文）を1つ生成してください。",
    "",
    "執筆前の再確認:",
    "- **出力の先頭は必ず `---`（frontmatter 開始）から。** その前に1文字も書かない（挨拶・リード禁止）。**`---` と `title:` 等の行頭にスペースを入れない。**",
    "- 業態は**相席ラウンジ**。キャバクラ・**キャスト・指名**など接客クラブの語は**一切使わない**。",
    "- **avoid_time は記事に書かない**。開店直後の人数最小は食事目的・出勤前層が含まれ、相席の質とは無関係なため。",
    "- **ML 2.0 推論由来の情報を優先**: `data_source=api/forecast_today` の場合、`draft_context.ml_signal_notes` は店舗別モデル推論の補助根拠。数値の言い換えではなく、来店判断のヒントとして短く反映する。",
    "- **「今日の結論」**ではピーク時間と混雑度を伝える。入店のおすすめ・入店しやすさの目安は**書かない**。",
    "- **draft_context.edition**: `evening_preview` なら今夜の**見通し・作戦**（未来のピークは予想）、`late_update` なら**実測に近い実況・答え合わせ**（断定しすぎない）。",
    "- **draft_context.secondary_wave.detected** が true なら、21〜22時台の急増を踏まえ**ゴールデンタイム**の紹介が可能（個人への結果保証はしない）。false なら無理に書かない。",
    "- **data_health** が厳しければサンプル不足・偏りを**正直に**書く。",
    "- **day_context** が存在する場合、曜日名を自然に記事へ反映し、**week_comparison** が available なら同曜日比較を1文で触れる。",
    "",
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
            description: "Markdown body only (## 見出し以降)。最低約40文字。frontmatter に含めない。",
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
