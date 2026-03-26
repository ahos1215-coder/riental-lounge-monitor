# GLOSSARY
Last updated: 2026-03-26

| 用語 | 意味（このリポジトリ） |
|------|------------------------|
| **夜窓（night window）** | JST で 当日 19:00〜翌 05:00 前後の来店ピーク想定帯。**Flask `/api/range` では切らない**。店舗 UI は `useStorePreviewData.ts`、LINE 下書きは `insightFromRange.ts`。 |
| **`avoid_time`** | 内部キー名は歴史的経緯で `avoid_time`。実体は窓内で `total` が**最も小さい**時間帯＝**空きやすい／狙い目**。`draftGenerator.ts` のプロンプトで **ポジティブ表現**に固定。 |
| **`blog_drafts`** | Supabase テーブル。Daily / Weekly / Editorial の 3種類すべてを保存。`content_type` / `is_published` / `edition` / `public_slug` で分類・管理。 |
| **`content_type`** | `blog_drafts` の分類カラム。`'daily'`（定時 AI 予測）/ `'weekly'`（週次 AI 週報）/ `'editorial'`（LINE 指示による分析ブログ）のいずれか。 |
| **`is_published`** | `blog_drafts` の公開フラグ。`daily` / `weekly` は生成完了時に `true`（自動）。`editorial` は LINE 承認後に `true`。 |
| **`edition`** | Daily の便名（`evening_preview` = 18:00 JST 便 / `late_update` = 21:30 JST 便）または `'weekly'`。 |
| **`public_slug`** | Editorial のアクセスパス。`/blog/[slug]` に使用。UNIQUE 制約（null 以外）。 |
| **`facts_id`** | `blog_drafts` の論理 ID。Daily は `auto_<store>_<edition>`、Weekly は `weekly_<store>`。UNIQUE 制約。 |
| **Daily Report** | `content_type='daily'` のコンテンツ。毎日 18:00 / 21:30 に GHA が自動生成・即時公開。URL は `/reports/daily/[store_slug]`（固定 URL 上書き）。 |
| **Weekly Report** | `content_type='weekly'` のコンテンツ。毎週水曜 06:30 JST に GHA が Fan-in Matrix で自動生成・即時公開。URL は `/reports/weekly/[store_slug]`（固定 URL 上書き）。 |
| **Editorial Blog** | `content_type='editorial'` のコンテンツ。LINE 指示 → AI 下書き → LINE 承認で公開。URL は `/blog/[public_slug]`。 |
| **Fan-in Matrix** | Weekly Report GHA の実行構成。Fan-out（38店舗並列）→ Fan-in（Artifact 集約・index.json 再構築・Git commit 1回）。 |
| **`--skip-index`** | `generate_weekly_insights.py` のフラグ。Fan-in の各 matrix ジョブで `index.json` 書き込みを抑制し、Fan-in ジョブで一括再構築するために使用。 |
| **`RANGE_LIMIT`** | `LINE_RANGE_LIMIT`（LINE 経路、既定 500）/ `BLOG_CRON_RANGE_LIMIT`（定時 Cron、既定 500）。小さいとインサイトが偏る。 |
| **n8n** | **ブログ/LINE 配管には使わない**（廃止方針）。 |
| **正本（source of truth）** | 混雑ログは Supabase `logs`。コンテンツ（下書き）は Supabase `blog_drafts`。Weekly JSON ファイルは GitHub。 |
