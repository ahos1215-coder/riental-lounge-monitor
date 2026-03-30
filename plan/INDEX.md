# INDEX（クイック参照）
Last updated: 2026-03-30 (Round 9 整合)  
Target commit: (see git)

**読む順・各ファイルの役割の一覧は [`README.md`](README.md) を正とする。**

---

## Repo Map（主要ディレクトリ）
- Backend（Flask）: `app.py`, `oriental/`
- Collector: `multi_collect.py`
- Frontend（Next.js）: `frontend/`
- Tests: `tests/`
- Scripts: `scripts/`
- Workflows: `.github/workflows/`（失敗通知の再利用: `notify-on-failure.yml`）
- Supabase migrations: `supabase/migrations/`

---

## Key Entry Points

### Backend
- `oriental/routes/data.py`（/api/range, /api/current）— `/api/current` の方針補足は **`plan/API_CURRENT.md`**
- `oriental/routes/forecast.py`（/api/forecast_*）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick など）
- `oriental/data/provider.py`（Supabase logs）

### Frontend — API Routes
- **LINE Webhook**: `frontend/src/app/api/line/route.ts`（draft / editorial_analysis / approve インテント処理）
- **Daily 生成**: `frontend/src/app/api/cron/blog-draft/route.ts`（`content_type='daily'`, `is_published=true`）
- **レート制限**: `frontend/src/lib/rateLimit/lineWebhookLimits.ts`

### Frontend — Lib
- **インサイト**: `frontend/src/lib/blog/insightFromRange.ts`
- **Gemini 下書き**: `frontend/src/lib/blog/draftGenerator.ts`
- **パイプライン統合**: `frontend/src/lib/blog/runBlogDraftPipeline.ts`（source → content_type/is_published 導出）
- **LINE 意図解析**: `frontend/src/lib/line/parseLineIntent.ts`（draft / editorial_analysis / approve）
- **Supabase CRUD**: `frontend/src/lib/supabase/blogDrafts.ts`
  - `fetchLatestPublishedReportByStore(storeSlug, contentType)` — daily/weekly 最新取得
  - `fetchPublishedEditorialBySlug(slug)` — editorial 公開記事取得
  - `publishEditorialBySlug(slug)` / `publishEditorialByFactsId(factsId)` — is_published → true
  - `fetchLatestUnpublishedEditorialByLineUser(lineUserId)` — 承認待ち下書き取得
- **localStorage ユーティリティ**: `frontend/src/lib/browser/meguribiStorage.ts`
- **ブログ frontmatter 検証**: `frontend/src/lib/blog/blogFrontmatter.ts`

### Frontend — Pages

| パス | ファイル | 説明 |
|------|----------|------|
| `/` | `page.tsx` + `home-client.tsx` | トップ |
| `/stores` | `stores/page.tsx` | 全店舗一覧 |
| `/store/[id]` | `store/[id]/page.tsx` | 店舗詳細 |
| `/reports/daily/[store_slug]` | `reports/daily/[store_slug]/page.tsx` | Daily Report |
| `/reports/weekly/[store_slug]` | `reports/weekly/[store_slug]/page.tsx` | Weekly Report |
| `/blog` | `blog/page.tsx` | Editorial ブログ一覧 |
| `/blog/[slug]` | `blog/[slug]/page.tsx` | Editorial 記事（is_published=true のみ）|
| `/compare` | `compare/page.tsx` | 店舗比較（最大3店舗、マージチャート） |
| `/insights/weekly` | → `/reports?tab=weekly` に 301 リダイレクト | |
| `/insights/weekly/[store]` | → `/reports/weekly/[store]` に 301 リダイレクト | |
| `/mypage` | `mypage/page.tsx` | ダッシュボード型マイページ（リッチカード・ML予測・レポートリンク） |

### Content / Batch
- Weekly insights: `scripts/generate_weekly_insights.py`（`--skip-index` フラグあり）→ `frontend/content/insights/weekly`（調整ガイド: `plan/WEEKLY_INSIGHTS_TUNING.md`）
- Public facts: `frontend/scripts/generate-public-facts.mjs` → `frontend/content/facts/public`
- Blog MDX: `frontend/content/blog`

### Workflows
- `trigger-blog-cron.yml` — Daily Report（matrix 38店舗, max-parallel: 15）
- `generate-weekly-insights.yml` — Weekly Report（Fan-in Matrix 38店舗, max-parallel: 10）
- `train-ml-model.yml` — ML 日次学習（Optuna HPO + Early Stopping）
- `x-auto-post.yml` — X 自動投稿（Daily 完了後 workflow_run）
- `generate-public-facts.yml` — Public Facts
- `retry-blog-draft-stores.yml` — Daily 失敗店舗再実行
- `blog-request.yml` — 手動ブログ依頼
- `check-pat-expiry.yml` — PAT 期限チェック + LINE 通知
- `e2e.yml` — Playwright E2E スモークテスト
- `blog-ci.yml` — CI
- `notify-on-failure.yml` — 失敗通知の再利用

### Supabase
- `supabase/migrations/20260326000000_blog_drafts_content_split.sql`（content_type / is_published / edition / public_slug 追加）

---

## Constraints（短縮版）
- Supabase `logs` が source of truth（Sheets/GAS は legacy fallback）
- `/api/range` は `store` + `limit` のみ（クエリ追加・サーバ側時間フィルタ禁止）
- **Flask は夜窓を採らない**。店舗 UI は `useStorePreviewData.ts`。**LINE 下書き**は `insightFromRange.ts`（取得済み JSON の集計）
- 二次会は map-link が本流
- **ブログ下書きに n8n は使わない**
- `blog_drafts` への書き込みは Next.js サーバー側からのみ（`SUPABASE_SERVICE_ROLE_KEY` はサーバー限定）
- `content_type` は `daily` / `weekly` / `editorial` の 3種類のみ
- `daily` / `weekly` は自動 `is_published=true`。`editorial` は LINE 承認が必要

用語: `GLOSSARY.md`
