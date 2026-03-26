# ROADMAP
Last updated: 2026-03-26
Target commit: (see git)

> **構想・フェーズ順・備忘の全文**は **`plan/VISION_AND_FUTURE.md`**。本ファイルは短いタスク一覧と「当面やらないこと」に絞る。

---

## 実装済み（2026-03-26 完了）

### コンテンツ戦略の完全リファクタ（Step 1–5）

| 分類 | URL | 生成 | 公開条件 |
|------|-----|------|---------|
| Daily Report | `/reports/daily/[store_slug]` | GHA 毎日 18:00/21:30 | `is_published=true`（自動）|
| Weekly Report | `/reports/weekly/[store_slug]` | GHA 毎週水曜 06:30 JST | `is_published=true`（自動）|
| Editorial Blog | `/blog/[slug]` | LINE 指示 + Gemini | LINE 承認で `is_published=true` |

**Step 1: DB スキーマ拡張**
- `blog_drafts` に `content_type` / `is_published` / `edition` / `public_slug` を追加
- Migration: `supabase/migrations/20260326000000_blog_drafts_content_split.sql`
- `facts_id` UNIQUE インデックス、`public_slug` UNIQUE（where not null）、複合インデックス

**Step 2: 生成パイプライン対応**
- `runBlogDraftPipeline.ts`: `source` から `content_type` / `is_published` を自動導出
- `/api/cron/blog-draft/route.ts`: `content_type='daily'`, `is_published=true` で保存
- `generate_weekly_insights.py`: Supabase upsert（`content_type='weekly'`, `is_published=true`）

**Step 3: ルーティング & UI**
- `/reports/daily/[store_slug]` ページ新設
- `/reports/weekly/[store_slug]` ページ新設
- `/blog/[slug]` は editorial かつ is_published=true のみ表示
- `sitemap.ts`: `/reports/daily/` + `/reports/weekly/` 全店舗分登録（旧 `auto-*` 廃止）
- `blog/page.tsx`: `autoCards` 削除 → Daily Report 誘導バナーに置き換え
- `/api/blog/latest-store-summary/route.ts`: href → `/reports/daily/[store_slug]`

**Step 4: LINE 承認フロー**
- `parseLineIntent.ts`: `approve` / `editorial_analysis` インテント追加
- `blogDrafts.ts`: `publishEditorialBySlug` / `publishEditorialByFactsId` / `fetchLatestUnpublishedEditorialByLineUser` 追加
- `route.ts`: `handleApproveIntent` / `handleDraftOrEditorialIntent` で処理分岐

**Step 5: GitHub Actions Matrix 最適化**
- Daily: `max-parallel: 20 → 15`
- Weekly: Fan-in Matrix 構成（Fan-out 38店舗並列 `max-parallel: 10` → Fan-in で index.json マージ・Git commit 1回）
- `generate_weekly_insights.py`: `--skip-index` フラグ追加

### Round 2: レポート一覧ページ + megribi_score + ナビゲーション統合

| 項目 | 内容 |
|------|------|
| `/reports/daily` 一覧ページ | Supabase から全店舗の最新 Daily Report を取得してカード表示 |
| `/reports/weekly` 一覧ページ | 同上（Weekly Report） |
| `/api/megribi_score` (Flask) | 全店舗の最新データから megribi_score を計算して返す API |
| `/api/megribi_score` (Next.js proxy) | Flask API へのプロキシ（CDN キャッシュ 2 分） |
| トップ「今夜のおすすめ」 | megribi_score TOP 5 をトップページに表示 |
| ヘッダーナビ | Daily / Weekly リンクを追加（モバイルでは非表示） |
| パンくず・導線 | Daily/Weekly 個別ページ → 一覧ページへの導線、店舗詳細 → レポート一覧への導線 |
| ブログページ | サイドバーに Weekly Report 一覧リンク追加、Daily リンクを一覧ページに変更 |
| サイトマップ | `/reports/daily` + `/reports/weekly` を static routes に追加 |
| `next.config.ts` | `/api/megribi_score` に CDN キャッシュヘッダー追加 |

---

## P0（次に着手しやすい項目）

- **`avoid_time` / プロンプト**: `draftGenerator.ts` で「混雑が落ち着いている目安」「提案型」の表現を固定（2026-03 ラベル追記済み）。ズレる場合は人手修正または微調整。
- **`LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT`**: LINE は既定 **500**。定時は **`BLOG_CRON_RANGE_LIMIT`**（既定 500）。偏りがあれば両方揃えて調整。
- **Web フロント**: 新規の「土台作り」より **既存画面の改善・見せ方・コンテンツ拡充**。進捗: `/`・`/store/[id]`・`/stores`・`/mypage`・`/reports/daily/`・`/reports/weekly/`・`/blog/[slug]` 実装済み。残りはブログ文言・細かな UI 等。
- **主要ドキュメントの継続同期**（`plan/*` と README の整合）
- **Weekly Insights の品質改善**（score 閾値・最小継続時間の運用調整。`plan/WEEKLY_INSIGHTS_TUNING.md`）
- **`/api/current`**: 当面は Flask 実装維持（`plan/API_CURRENT.md`）。Supabase 直取得へ寄せるかは別タスク。

## P1

- 週次 Insights の可視化強化（**実装済み**: `series_compact`＋`WeeklyStoreCharts.tsx`。追加の系列や説明文は任意）
- Editorial ブログの充実（LINEから定期的に分析記事を作る運用の確立）
- ~~`/reports/daily/` / `/reports/weekly/` ページの UX 改善（ナビゲーション・一覧ページ等）~~ → **実装済み（Round 2）**
- 監視・運用の可視化（ログの整理、Render/Vercel 運用の整理）
- **GitHub Actions の失敗通知**（**実装済み**: `OPS_NOTIFY_WEBHOOK_URL` + `notify-on-failure.yml`。定時ブログの部分失敗は `summarize-blog-matrix` が steps まで確認）
- **Gemini 出力の構造化**: frontmatter と本文の分離（Zod 検証は追加済み）
- **OGP / メタデータ**（**実装済み**）。**X（Twitter）API 連携・投稿用 API ルート**（未実装・構想段階）

## P2

- 複数店舗/ブランドの拡張（表示/UI の拡張）
- ~~`/reports/daily/` の一覧ページ~~ → **実装済み（Round 2）**
- ~~`/reports/weekly/` の一覧ページ~~ → **実装済み（Round 2）**
- 予測の精度・運用（オンザフライ学習 vs 定期学習モデル等）
- **PWA / Web Push**
- **Stripe・課金・プレミアム予測**（外部助言: 個人開発では当面優先度を下げてよい）

## 当面やらない（方針）

- **PR の URL を LINE に自動送信する**仕組み（必要になったら設計から検討。**n8n は使わない**）。
- `/api/range` へのクエリ追加・サーバ側時間フィルタ。
- フロントから Supabase 直アクセス。

## 将来オプション（仕様未定）

- **公開までフル自動**（環境変数 ON/OFF 等）。**ガードレール・Staging 前提**。`VISION_AND_FUTURE.md` §5。

## スケール・SEO・Cron（方針の要約）

- **SEO（Daily Report）**: `/reports/daily/[store_slug]` は固定 URL（上書き運用）。カニバリゼーションを避け鮮度（Freshness）を優先。Weekly も同様に `/reports/weekly/[store_slug]` で固定 URL。
- **定時ブログの時計**: **cron-job.org** が正本（JST 18:00 / 21:30 に GitHub `workflow_dispatch` を呼び出す）。`trigger-blog-cron.yml` は `schedule` を持たず `workflow_dispatch` 専用。`vercel.json` の Cron は**使わない**（削除済み）。
- **Weekly の Git コミット**: Fan-in ジョブが 1回のみ commit するため、並列書き込みの競合なし。
- **X 自動投稿**: 全店舗一斉ポストは行わず、開始時は **人気トップ5＋長崎店**に限定（API・シャドウバンリスク回避）。

## 未実装メモ

- 定時ブログは `GET /api/cron/blog-draft`（**GHA** から `GET` + `edition` / `source` + **`store` 必須**）で実装済み。全店は **matrix 並列**（`max-parallel: 15`）、非同期キューは **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。
- Weekly の Fan-in Matrix は実装済み。さらなる並列度アップや Render API への負荷増大時は `max-parallel` を調整。
