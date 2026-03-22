import { STORES, type StoreMeta } from "@/app/config/stores";

function todayYmdTokyo(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export type ParsedLineIntent =
  | {
      kind: "draft";
      store: StoreMeta;
      dateYmd: string;
      factsId: string;
      /** Remaining free text after store/date tokens (topic / style hints) */
      topicHint: string;
    }
  | { kind: "help" }
  | { kind: "error"; message: string };

/** 公開 facts / 下書き用の安定 ID（店舗 slug + 日付） */
export function buildFactsId(slug: string, dateYmd: string): string {
  const compact = dateYmd.replace(/-/g, "");
  return `${slug}-tonight-${compact}`;
}

/**
 * Parse user text from LINE.
 * Examples: "渋谷 今夜", "shibuya", "ol_shibuya 2025-12-21", "新宿　お願い　混雑について"
 */
export function parseLineIntent(text: string): ParsedLineIntent {
  const trimmed = text.trim();
  if (!trimmed) {
    return { kind: "error", message: "メッセージが空です。" };
  }

  const lower = trimmed.toLowerCase();
  if (lower === "help" || lower === "ヘルプ" || lower === "?" || lower === "？") {
    return { kind: "help" };
  }

  const dateMatch = trimmed.match(/\b(\d{4}-\d{2}-\d{2})\b/);
  const dateYmd = dateMatch ? dateMatch[1] : todayYmdTokyo();

  let rest = trimmed.replace(/\b\d{4}-\d{2}-\d{2}\b/g, " ").trim();
  rest = rest
    .replace(/(今夜|今日|下書き|記事|ブログ)/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const tokens = rest.length ? rest.split(/\s/).filter(Boolean) : [];

  const matched = resolveStoreFromTokens(tokens);
  if (!matched) {
    return {
      kind: "error",
      message:
        "店舗名が分かりません（例: 渋谷、shibuya、ol_shinjuku）。「ヘルプ」で使い方を表示します。",
    };
  }

  const { store, consumedTokens } = matched;
  const topicTokens = tokens.filter((t) => !consumedTokens.includes(t));
  const topicHint = topicTokens.join(" ").trim();

  return {
    kind: "draft",
    store,
    dateYmd,
    factsId: buildFactsId(store.slug, dateYmd),
    topicHint,
  };
}

function resolveStoreFromTokens(tokens: string[]): { store: StoreMeta; consumedTokens: string[] } | null {
  if (tokens.length === 0) {
    // Allow message that is only a known label without spaces (e.g. single token already in rest)
    return null;
  }

  // Longest label first for stable matching
  const sorted = [...STORES].sort((a, b) => b.label.length - a.label.length);

  for (const token of tokens) {
    const t = token.trim();
    if (!t) continue;
    const tl = t.toLowerCase();

    for (const store of STORES) {
      if (tl === store.slug || tl === store.storeId.toLowerCase()) {
        return { store, consumedTokens: [token] };
      }
    }

    for (const store of sorted) {
      if (store.label.includes(t) || t === store.label) {
        return { store, consumedTokens: [token] };
      }
      if (store.areaLabel.includes(t) && t.length >= 2) {
        return { store, consumedTokens: [token] };
      }
    }
  }

  // Combine two tokens for labels like "名古屋 錦"
  for (let i = 0; i < tokens.length - 1; i++) {
    const pair = `${tokens[i]} ${tokens[i + 1]}`;
    for (const store of sorted) {
      if (store.label === pair || store.label.includes(pair)) {
        return { store, consumedTokens: [tokens[i], tokens[i + 1]] };
      }
    }
  }

  return null;
}
