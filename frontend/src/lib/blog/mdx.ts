/**
 * 自動生成 MDX（Daily / Weekly レポート・編集記事）の前処理ヘルパー。
 *
 * 以前は同じ実装が API ルート2本とページ3本に手書きコピーされていた（stripFrontmatter は
 * 5ファイルにバイト一致で存在）。「レポート本文をどう切り出しているか」を1ファイルに集約する。
 *
 * 注意: frontmatter の判定は `---\n` 始まり・`\n---\n` 終端のみ（CRLF 非対応）。
 * これは移設前の5実装が共有していた制約をそのまま引き継いだもので、生成側（scripts/）が
 * LF で書いているため実害は無い。CRLF 対応は別途の判断とする。
 */

/** 先頭の YAML frontmatter ブロックを取り除く。frontmatter が無ければそのまま返す。 */
export function stripFrontmatter(raw: string): string {
  if (!raw.startsWith("---\n")) return raw;
  const end = raw.indexOf("\n---\n", 4);
  if (end < 0) return raw;
  return raw.slice(end + 5).trimStart();
}

/**
 * 先頭付近の見出し行（# / ## / ###）をタイトル候補として抽出する。
 *
 * `skipBlank` は「見出し記号の後が空白だけだった行」の扱い:
 *   - true（既定 / blog/[slug] の挙動）… その行を飛ばして次の見出しを探す
 *   - false（/api/reports/store-summary の従来挙動）… 空文字 "" をそのまま返す
 * API レスポンスの値を変えないため、呼び出し側で明示的に選ぶ。
 * frontmatter の除去は行わないので、必要なら stripFrontmatter を先に通すこと。
 */
export function extractFirstHeading(
  mdx: string,
  { skipBlank = true }: { skipBlank?: boolean } = {},
): string | null {
  for (const line of mdx.split("\n")) {
    const m = line.match(/^#{1,3}\s+(.+)/);
    if (!m) continue;
    const text = m[1].trim();
    if (!skipBlank) return text;
    if (text) return text;
  }
  return null;
}

/** 見出し・箇条書き・引用・コードブロック以外の最初の段落を抽出する（既定120文字で切り詰め）。 */
export function extractFirstParagraph(mdx: string, maxLen = 120): string | null {
  for (const rawLine of mdx.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^#{1,6}\s+/.test(line)) continue;
    if (/^[-*+]\s+/.test(line)) continue;
    if (/^\d+\.\s+/.test(line)) continue;
    if (line.startsWith(">")) continue;
    if (line.startsWith("```")) continue;
    const truncated = line.length > maxLen ? `${line.slice(0, maxLen)}…` : line;
    return truncated;
  }
  return null;
}

/** MDX 本文から箇条書き（- / * で始まる行）を最大 max 件抽出する（frontmatter は内部で除去）。 */
export function extractBullets(mdx: string, max = 3): string[] {
  const body = stripFrontmatter(mdx);
  const bullets: string[] = [];
  for (const line of body.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const text = trimmed.replace(/^[-*]\s+/, "").trim();
      if (text.length > 0) bullets.push(text);
    }
    if (bullets.length >= max) break;
  }
  return bullets;
}

/** `## <heading>` セクション直下の箇条書き行を、次の `##` 手前まで最大 max 件返す。 */
export function pickSectionLines(md: string, heading: string, max = 4): string[] {
  const h = `## ${heading}`.trim();
  const idx = md.indexOf(h);
  if (idx < 0) return [];
  const rest = md.slice(idx + h.length);
  const next = rest.search(/\n##\s+/);
  const block = (next >= 0 ? rest.slice(0, next) : rest).trim();
  const lines = block
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
    .filter((s) => s.startsWith("- "))
    .map((s) => s.replace(/^-+\s+/, "").trim());
  return lines.slice(0, Math.max(1, max));
}

/** 見出し・箇条書き以外の最初の非空行を返す（既定120文字で切り詰め）。 */
export function pickFirstNonEmptyLine(md: string, maxLen = 120): string | null {
  const line = md
    .split("\n")
    .map((s) => s.trim())
    .find((s) => s && !s.startsWith("#") && !s.startsWith("- "));
  if (!line) return null;
  return line.length > maxLen ? `${line.slice(0, maxLen - 1)}…` : line;
}
