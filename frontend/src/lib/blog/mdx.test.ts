import { describe, expect, it } from "vitest";

import {
  extractBullets,
  extractFirstHeading,
  extractFirstParagraph,
  pickFirstNonEmptyLine,
  pickSectionLines,
  stripFrontmatter,
} from "./mdx";

describe("stripFrontmatter（5ファイルから集約した実装の挙動を固定）", () => {
  it("frontmatter があれば取り除き、先頭の空白も落とす", () => {
    const raw = "---\ntitle: x\nsource: y\n---\n\n# 見出し\n本文";
    expect(stripFrontmatter(raw)).toBe("# 見出し\n本文");
  });

  it("frontmatter が無ければそのまま返す", () => {
    expect(stripFrontmatter("# 見出し\n本文")).toBe("# 見出し\n本文");
  });

  it("開始はあるが終端 `\\n---\\n` が無ければそのまま返す", () => {
    const raw = "---\ntitle: x\n";
    expect(stripFrontmatter(raw)).toBe(raw);
  });

  it("CRLF は非対応（移設前と同じく素通しする）", () => {
    const raw = "---\r\ntitle: x\r\n---\r\n# 見出し";
    expect(stripFrontmatter(raw)).toBe(raw);
  });
});

describe("extractFirstHeading — skipBlank で2つの既存挙動を作り分ける", () => {
  it("最初の # / ## / ### 見出しを返す", () => {
    expect(extractFirstHeading("本文\n## 今日の結論\n- a")).toBe("今日の結論");
  });

  it("見出しが無ければ null", () => {
    expect(extractFirstHeading("本文だけ")).toBeNull();
  });

  it("skipBlank=true（既定 / blog）は空白だけの見出しを飛ばして次を探す", () => {
    expect(extractFirstHeading("##   \n## 本命")).toBe("本命");
  });

  it("skipBlank=false（store-summary の従来挙動）は空文字をそのまま返す", () => {
    expect(extractFirstHeading("##   \n## 本命", { skipBlank: false })).toBe("");
  });

  it("frontmatter は除去しない（呼び出し側の責務）", () => {
    expect(extractFirstHeading("---\ntitle: x\n---\n## 見出し")).toBe("見出し");
  });
});

describe("extractFirstParagraph", () => {
  it("見出し・箇条書き・番号・引用・コード柵の行を飛ばして最初の段落を返す", () => {
    const md = "# 見出し\n- 箇条書き\n1. 番号\n> 引用\n```\n本文の段落";
    expect(extractFirstParagraph(md)).toBe("本文の段落");
  });

  it("飛ばすのは ``` の行だけで、コードブロックの中身は段落として拾う（移設前と同じ）", () => {
    expect(extractFirstParagraph("```\ncode\n```\n本文")).toBe("code");
  });

  it("120文字を超えると 120文字 + … （合計121文字）に切り詰める（移設前と同じ）", () => {
    const out = extractFirstParagraph("あ".repeat(200));
    expect(out).toBe(`${"あ".repeat(120)}…`);
  });

  it("段落が無ければ null", () => {
    expect(extractFirstParagraph("# 見出しだけ")).toBeNull();
  });
});

describe("extractBullets（frontmatter を内部で除去する）", () => {
  it("- / * の行を最大 max 件返す", () => {
    const md = "---\ntitle: x\n---\n# h\n- 一つ目\n* 二つ目\n- 三つ目\n- 四つ目";
    expect(extractBullets(md, 3)).toEqual(["一つ目", "二つ目", "三つ目"]);
  });

  it("箇条書きが無ければ空配列", () => {
    expect(extractBullets("本文だけ")).toEqual([]);
  });
});

describe("pickSectionLines", () => {
  it("指定見出し直下の箇条書きを次の ## 手前まで返す", () => {
    const md = "## 今日の結論\n- A\n- B\n\n## 次の節\n- C";
    expect(pickSectionLines(md, "今日の結論", 4)).toEqual(["A", "B"]);
  });

  it("見出しが無ければ空配列", () => {
    expect(pickSectionLines("## ほか\n- A", "今日の結論")).toEqual([]);
  });
});

describe("pickFirstNonEmptyLine", () => {
  it("見出し・箇条書き以外の最初の非空行を返す", () => {
    expect(pickFirstNonEmptyLine("\n# h\n- b\n本文")).toBe("本文");
  });

  it("120文字を超えると 119文字 + … （合計120文字）に切り詰める（移設前と同じ）", () => {
    const out = pickFirstNonEmptyLine("あ".repeat(200));
    expect(out).toBe(`${"あ".repeat(119)}…`);
  });
});
