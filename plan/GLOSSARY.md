# GLOSSARY
Last updated: 2026-04-18

| 用語 | 意味（このリポジトリ） |
|------|------------------------|
| **夜窓（night window）** | JST で 当日 19:00〜翌 05:00 前後の来店ピーク想定帯。**Flask `/api/range` では切らない**。店舗 UI は `useStorePreviewData.ts`、LINE 下書きは `insightFromRange.ts`。 |
| **`src_brand`** | Supabase `logs` テーブルのブランド識別カラム。`'oriental'`（Oriental Lounge + ag、計38店舗）/ `'aisekiya'`（相席屋、6店舗、2026-04-17〜）。 |
| **`brand`（StoreMeta）** | `frontend/src/data/stores.json` の店舗ブランド属性。`"oriental"` / `"aisekiya"` / `"jis"`（未実装）。`config/stores.ts` で型定義。 |
| **schema_version** | ML モデルの特徴量スキーマバージョン。**v5 (2026-04-13〜)** が現行。22列（v4 の 21 + `extreme_weather`）。`metadata.json` と `preprocess.py` の `FEATURE_COLUMNS` が一致必須。 |
| **LightGBM** | 推論モデルの実装。XGBoost から 2026-04-12 に移行。メモリフットプリント約半分、学習時間 5 分。互換性のため `model_xgb.py` 内で実装、XGBoost フォールバック保持。 |
| **逆算ロジック（相席屋）** | 相席屋は人数ではなくパーセンテージ表示のため、`(座席数+VIP)×2 × %` で推定人数を逆算。`AISEKIYA_STORES` dict に座席数マスタを保持。**「※推計値」と免責ページに明記**。 |
| **`avoid_time`** | 内部キー名は歴史的経緯で `avoid_time`。実体は窓内で `total` が**最も小さい**時間帯。**記事には一切使わない**（開店直後は食事目的・出勤前層が含まれ、相席の質とは無関係なため。`draftGenerator.ts` のプロンプトで明示的に禁止）。記事で出力するのは `peak_time` と `crowd_label` のみ。 |
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
