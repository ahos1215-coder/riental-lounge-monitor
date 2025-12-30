import fs from "node:fs";
import path from "node:path";

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function writeText(fp, text) {
  ensureDir(path.dirname(fp));
  fs.writeFileSync(fp, text.replace(/^\uFEFF/, ""), "utf8"); // UTF-8 no BOM
}

function writeJson(fp, obj) {
  writeText(fp, JSON.stringify(obj, null, 2) + "\n");
}

function parseArgs(argv) {
  const out = {
    request_id: "",
    store_id: "",
    target_date: "",
    kind: "",
    angle: "",
    tone: "",
    slug: "",
    notes: "",
  };

  for (let i = 0; i < argv.length; i++) {
    const a = String(argv[i] ?? "");
    const next = argv[i + 1];

    const take = () => {
      if (typeof next === "string" && next.length) {
        i++;
        return next;
      }
      return "";
    };

    if (a === "--request_id" || a === "--request-id") out.request_id = String(take());
    else if (a.startsWith("--request_id=")) out.request_id = a.split("=", 2)[1] ?? "";
    else if (a.startsWith("--request-id=")) out.request_id = a.split("=", 2)[1] ?? "";

    else if (a === "--store_id" || a === "--store-id") out.store_id = String(take());
    else if (a.startsWith("--store_id=")) out.store_id = a.split("=", 2)[1] ?? "";
    else if (a.startsWith("--store-id=")) out.store_id = a.split("=", 2)[1] ?? "";

    else if (a === "--target_date" || a === "--target-date") out.target_date = String(take());
    else if (a.startsWith("--target_date=")) out.target_date = a.split("=", 2)[1] ?? "";
    else if (a.startsWith("--target-date=")) out.target_date = a.split("=", 2)[1] ?? "";

    else if (a === "--kind") out.kind = String(take());
    else if (a.startsWith("--kind=")) out.kind = a.split("=", 2)[1] ?? "";

    else if (a === "--angle") out.angle = String(take());
    else if (a.startsWith("--angle=")) out.angle = a.split("=", 2)[1] ?? "";

    else if (a === "--tone") out.tone = String(take());
    else if (a.startsWith("--tone=")) out.tone = a.split("=", 2)[1] ?? "";

    else if (a === "--slug") out.slug = String(take());
    else if (a.startsWith("--slug=")) out.slug = a.split("=", 2)[1] ?? "";

    else if (a === "--notes") out.notes = String(take());
    else if (a.startsWith("--notes=")) out.notes = a.split("=", 2)[1] ?? "";
  }
  return out;
}

function ymd8(ymd) {
  return String(ymd ?? "").trim().replaceAll("-", "");
}

function fmtYmdTokyo(d) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function ymdPlusDays(ymd, days) {
  const base = new Date(`${ymd}T00:00:00+09:00`);
  const d = new Date(base.getTime() + days * MS_PER_DAY);
  return fmtYmdTokyo(d);
}

function nightWindowIso(ymd) {
  const from = `${ymd}T19:00:00+09:00`;
  const toYmd = ymdPlusDays(ymd, 1);
  const to = `${toYmd}T05:00:00+09:00`;
  return { from, to, label: "Tonight" };
}

function yamlDoubleQuote(s) {
  const v = String(s ?? "");
  return `"${v.replaceAll("\\\\", "\\\\\\\\").replaceAll('"', '\\"')}"`;
}

function pickCategory(kind) {
  if (kind === "weekly") return "prediction";
  if (kind === "howto") return "beginner";
  return "guide";
}

function pickPeriod(kind) {
  if (kind === "weekly") return "this_week";
  if (kind === "howto") return "generic";
  return "tonight";
}

function defaultTitle({ store_id, kind }) {
  if (kind === "weekly") return `今週の${store_id}、混みやすいのは何時？（下書き）`;
  if (kind === "howto") return `${store_id}の使い方メモ（下書き）`;
  return `今夜の${store_id}、狙い目は21:30台（下書き）`;
}

function defaultDescription({ kind }) {
  if (kind === "howto") return "10秒でわかる結論：初見で困らない動き方だけ先に。";
  return "10秒でわかる結論：到着目安と避けたい時間だけ先に。";
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const request_id = args.request_id.trim();
  const store_id = args.store_id.trim();
  const target_date = args.target_date.trim();
  const kind = args.kind.trim();

  if (!request_id || !store_id || !target_date || !kind) {
    throw new Error("missing required: request_id, store_id, target_date, kind");
  }

  const slug = (args.slug && args.slug.trim()) || `${store_id}-${kind}-${ymd8(target_date)}`;
  const title = defaultTitle({ store_id, kind });
  const description = defaultDescription({ kind });
  const category = pickCategory(kind);
  const period = pickPeriod(kind);

  // GitHub Actions で working-directory: frontend を前提
  const frontendRoot = process.cwd();
  const blogPath = path.join(frontendRoot, "content", "blog", `${slug}.mdx`);
  const factsPath = path.join(frontendRoot, "content", "facts", "public", `${slug}.json`);

  const mdx =
    [
      "---",
      `title: ${yamlDoubleQuote(title)}`,
      `description: ${yamlDoubleQuote(description)}`,
      `date: ${yamlDoubleQuote(target_date)}`,
      `category: ${yamlDoubleQuote(category)}`,
      `level: ${yamlDoubleQuote("easy")}`,
      `store: ${yamlDoubleQuote(store_id)}`,
      `period: ${yamlDoubleQuote(period)}`,
      `facts_id: ${yamlDoubleQuote(slug)}`,
      `factsId: ${yamlDoubleQuote(slug)}`,
      `facts_visibility: ${yamlDoubleQuote("show")}`,
      `draft: true`,
      `request_id: ${yamlDoubleQuote(request_id)}`,
      args.angle.trim() ? `angle: ${yamlDoubleQuote(args.angle.trim())}` : null,
      args.tone.trim() ? `tone: ${yamlDoubleQuote(args.tone.trim())}` : null,
      "---",
      "",
      "## 10秒まとめ",
      "- 到着目安：21:30台（仮）",
      "- 避けたい時間：20:00台（仮）",
      "",
      "## 今日の一言",
      "短い一文で人間味。",
      "",
      "## 理由はこれ（根拠は1つ）",
      "本文は「理由1つ」だけ。数字を散らさず、必要なら下に隔離。",
      "",
      "## 初心者メモ",
      "失敗しない動き方。",
      "",
      "## くわしく（任意）",
      "グラフや注意点はここに隔離。",
      "",
      args.notes.trim()
        ? "---\n\n## 依頼メモ（そのまま公開しない）\n\n" + args.notes.trim() + "\n"
        : "",
    ]
      .filter((x) => x != null)
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trimEnd() + "\n";

  writeText(blogPath, mdx);

  const range = nightWindowIso(target_date);
  const facts = {
    facts_id: slug,
    store: store_id,
    range,
    insight: { peak_time: "", avoid_time: "", crowd_label: "" },
    quality_flags: {
      notes: [
        "stub: generated by new-blog-request.mjs",
        `request_id:${request_id}`,
        `kind:${kind}`,
        args.angle.trim() ? `angle:${args.angle.trim()}` : null,
        args.tone.trim() ? `tone:${args.tone.trim()}` : null,
      ].filter(Boolean),
    },
  };

  writeJson(factsPath, facts);
  console.log(JSON.stringify({ slug, blogPath, factsPath }));
}

await main();