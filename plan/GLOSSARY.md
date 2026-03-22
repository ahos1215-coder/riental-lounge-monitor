# GLOSSARY
Last updated: 2026-03-21

| 用語 | 意味（このリポジトリ） |
|------|------------------------|
| **夜窓（night window）** | JST で 当日 19:00〜翌 05:00 前後の来店ピーク想定帯。**Flask `/api/range` では切らない**。店舗 UI は `useStorePreviewData.ts`、LINE 下書きは `insightFromRange.ts`。 |
| **`avoid_time`** | 内部キー名は歴史的経緯で `avoid_time`。実体は窓内で `total` が**最も小さい**時間帯＝**空きやすい／狙い目**。Gemini 下書きは `draftGenerator.ts` のプロンプトで **ポジティブ表現**に固定。読者向けラベルは「狙い目の時間」等。 |
| **`blog_drafts`** | Supabase テーブル。LINE 経路で生成した MDX 下書き等を保存。**サイト公開 MDX とは別**（半自動運用）。 |
| **`RANGE_LIMIT`** | `frontend/src/app/api/line/route.ts` 内。`/api/range` の `limit`。小さいとインサイトが偏る。 |
| **n8n** | **ブログ/LINE 配管には使わない**（廃止方針）。 |
| **正本（source of truth）** | 混雑ログは Supabase `logs`。 |
