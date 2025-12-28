import fs from "node:fs";
import path from "node:path";

function fmtYmdTokyo(d) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function slugToYmd(slug) {
  // expecting ...-yyyymmdd at tail
  const m = String(slug).match(/(\d{4})(\d{2})(\d{2})$/);
  if (!m) return "";
  return `${m[1]}-${m[2]}-${m[3]}`;
}

function safeReadJson(fp) {
  try {
    const s = fs.readFileSync(fp, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function writeJson(fp, obj) {
  fs.mkdirSync(path.dirname(fp), { recursive: true });
  fs.writeFileSync(fp, JSON.stringify(obj, null, 2) + "\n", "utf8");
}

function pickStoreId(j) {
  // store can be string or object; accept multiple aliases
  if (typeof j?.store === "string" && j.store.trim()) return j.store.trim();
  if (typeof j?.store_id === "string" && j.store_id.trim()) return j.store_id.trim();
  if (typeof j?.storeId === "string" && j.storeId.trim()) return j.storeId.trim();
  if (typeof j?.store?.id === "string" && j.store.id.trim()) return j.store.id.trim();
  if (typeof j?.store?.slug === "string" && j.store.slug.trim()) return j.store.slug.trim();
  return "";
}

function pickFactsId(j, filenameSlug) {
  const v =
    (typeof j?.facts_id === "string" && j.facts_id.trim() && j.facts_id.trim()) ||
    (typeof j?.factsId === "string" && j.factsId.trim() && j.factsId.trim()) ||
    (typeof j?.facts_id_public === "string" && j.facts_id_public.trim() && j.facts_id_public.trim()) ||
    (typeof j?.factsIdPublic === "string" && j.factsIdPublic.trim() && j.factsIdPublic.trim()) ||
    filenameSlug ||
    "";
  return v;
}

function pickDate(j, slug) {
  const fromSlug = slugToYmd(slug);
  if (fromSlug) return fromSlug;
  if (typeof j?.date === "string" && j.date.trim()) return j.date.trim();
  if (typeof j?.target_date === "string" && j.target_date.trim()) return j.target_date.trim();
  if (typeof j?.targetDate === "string" && j.targetDate.trim()) return j.targetDate.trim();
  return "";
}

function main() {
  const frontendRoot = process.cwd(); // run inside frontend
  const factsDir = path.join(frontendRoot, "content", "facts", "public");
  const indexPath = path.join(factsDir, "index.json");

  if (!fs.existsSync(factsDir)) {
    throw new Error(`not found: ${factsDir}`);
  }

  const files = fs.readdirSync(factsDir).filter((f) => f.endsWith(".json") && f !== "index.json");
  const items = [];

  for (const f of files) {
    const fp = path.join(factsDir, f);
    const j = safeReadJson(fp);
    if (!j) continue;

    const filenameSlug = path.basename(f, ".json");
    const slug = pickFactsId(j, filenameSlug);
    const storeId = pickStoreId(j);
    const date = pickDate(j, slug);

    if (!slug || !storeId || !date) continue;

    items.push({
      slug,
      store: { id: storeId },
      date,
      level: "easy",
    });
  }

  items.sort((a, b) => String(a.slug).localeCompare(String(b.slug)));

  const latest_by_store = {};
  for (const it of items) {
    const sid = it.store?.id ?? "";
    if (!sid) continue;
    const cur = latest_by_store[sid];
    // slug末尾がyyyymmddなので辞書順で最大が最新になりやすい
    if (!cur || String(it.slug) > String(cur)) latest_by_store[sid] = it.slug;
  }

  const payload = {
    generated_at: fmtYmdTokyo(new Date()),
    facts: items,
    latest_by_store,
  };

  writeJson(indexPath, payload);
  console.log(`wrote: ${path.relative(frontendRoot, indexPath)} (facts=${items.length})`);
}

main();