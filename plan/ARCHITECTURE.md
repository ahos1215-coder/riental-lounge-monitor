# ARCHITECTURE
Last updated: 2026-03-26
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores/blog_drafts) → Flask API (Render) → Next.js (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- Night window（19:00–05:00）: **店舗 UI** は `useStorePreviewData.ts`。**LINE 下書き**は同じ窓定義を **`insightFromRange.ts`**（Next サーバー）で適用。Flask は夜窓を採らない。
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は GitHub Actions で生成し、`frontend/content/*` にコミット
- コンテンツは 3種類に分類（`blog_drafts.content_type`）:
  - **`daily`**: GitHub Actions 定時 → Supabase → `/reports/daily/[store_slug]`
  - **`weekly`**: GitHub Actions 週次 → Supabase + ファイル → `/reports/weekly/[store_slug]`
  - **`editorial`**: LINE 指示 → Supabase（未公開）→ LINE 承認 → `/blog/[slug]`

## Data Flow

### 1) 収集
`multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む。`/tasks/tick` はレガシー。

### 2) Flask API
`/api/range` / `/api/current` / `/api/forecast_*` を提供。`/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却。

### 3) Next.js ページ・API Routes

| パス | データ取得元 |
|------|--------------|
| `/` | `/api/range` + `getAllPostMetas()`（静的 MDX）|
| `/store/[id]` | `/api/range` + `/api/forecast_today` |
| `/stores` | `/api/range_multi` |
| `/reports/daily/[store_slug]` | Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`）|
| `/reports/weekly/[store_slug]` | Supabase `blog_drafts`（`content_type='weekly'`, `is_published=true`）|
| `/insights/weekly/[store]` | `frontend/content/insights/weekly/<store>/<date>.json`（fs）|
| `/blog/[slug]` | Supabase `blog_drafts`（`content_type='editorial'`, `is_published=true`）|

### 4) GitHub Actions バッチ

```
Daily Report（毎日 18:00 / 21:30 JST）:
  trigger-blog-cron.yml
  └─ matrix: 38 store × 独立ジョブ (max-parallel: 15)
     └─ GET /api/cron/blog-draft?store=<slug>&edition=...
        └─ Supabase blog_drafts (content_type='daily', is_published=true)

Weekly Report（毎週水曜 06:30 JST）:
  generate-weekly-insights.yml [Fan-in 構成]
  ├─ generate-store: 38 store × 独立ジョブ (max-parallel: 10)
  │   ├─ generate_weekly_insights.py --stores <one_store> --skip-index
  │   ├─ Supabase upsert (content_type='weekly', is_published=true)
  │   └─ upload Artifact: weekly-<store>/
  └─ collect-and-commit: Fan-in
      ├─ download all Artifacts
      ├─ rebuild index.json (Python inline)
      ├─ pytest
      └─ git commit & push (1回のみ)
```

### 5) LINE 承認フロー（Editorial）
```
LINE メッセージ（「分析して」等）
  → POST /api/line
    → parseLineIntent: editorial_analysis
    → /api/range + /api/forecast_today (BACKEND_URL 経由)
    → insightFromRange.ts
    → draftGenerator.ts (Gemini)
    → Supabase blog_drafts (content_type='editorial', is_published=false)
    → LINE 返信（「確認してから公開してください」）

LINE メッセージ（「公開」「ok」等）
  → POST /api/line
    → parseLineIntent: approve
    → blog_drafts の is_published を true に更新
    → LINE 返信（/blog/[public_slug] の URL）
```

## Contracts / Constraints
- `/api/range` の公開契約は `store` + `limit` のみ
  - server-side の時間フィルタ禁止。night window は **店舗 UI のフロント**および **LINE 用 `insightFromRange.ts`** で、取得済み行に対して実施
- Secrets は環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）
- 既存エンドポイント互換性を維持（/healthz, /api/meta, /api/current, /api/range, /api/forecast_*, /tasks/*）
- Second venues は map-link 方式を維持（Places API 依存に戻さない）
- Supabase への書き込みは Next.js サーバー側からのみ（`SUPABASE_SERVICE_ROLE_KEY` はサーバー限定）

## Blog Cron Scale Strategy（実装済み）
- **Daily**: GitHub Actions `trigger-blog-cron.yml` が `matrix` で 38店舗を **`max-parallel: 15`** で並列処理。1 job = 1 store = 1 API リクエスト。504 が出た店舗は `continue-on-error` で全体を止めず、`retry-blog-draft-stores.yml` で再実行可能。
- **Weekly**: `generate-weekly-insights.yml` が Fan-in Matrix 構成。Fan-out（`max-parallel: 10`）で各店舗を独立実行 → Fan-in で `index.json` を一元マージし Git commit 1回。Supabase upsert は各ジョブ内で完結するため競合なし。

## Key Files

### Backend
- `oriental/routes/data.py`（/api/range, /api/current）
- `oriental/routes/forecast.py`（/api/forecast_*）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick など）
- `oriental/data/provider.py`（Supabase logs provider）
- `multi_collect.py`（収集ロジック）

### Frontend
- `frontend/src/app/api/*/route.ts`（backend proxy）
- `frontend/src/app/api/line/route.ts`（LINE Messaging webhook → draft/editorial/approve）
- `frontend/src/app/api/cron/blog-draft/route.ts`（daily report 生成、`content_type='daily'`）
- `frontend/src/lib/blog/insightFromRange.ts`（LINE 用インサイト・窓計算）
- `frontend/src/lib/blog/draftGenerator.ts`（Gemini 下書き）
- `frontend/src/lib/blog/runBlogDraftPipeline.ts`（source から content_type / is_published を導出）
- `frontend/src/lib/line/parseLineIntent.ts`（draft / editorial_analysis / approve インテント）
- `frontend/src/lib/supabase/blogDrafts.ts`（Supabase CRUD: fetch/upsert/publish）
- `frontend/src/app/hooks/useStorePreviewData.ts`（店舗 UI 夜窓）
- `frontend/src/app/reports/daily/[store_slug]/page.tsx`（Daily Report ページ）
- `frontend/src/app/reports/weekly/[store_slug]/page.tsx`（Weekly Report ページ）
- `frontend/src/app/blog/[slug]/page.tsx`（Editorial ブログ、is_published=true のみ）
- `frontend/src/app/insights/weekly/**`（週次インサイトページ）
- `frontend/src/app/sitemap.ts`（/reports/daily + weekly を全店舗分登録）

### Content / Batch
- `scripts/generate_weekly_insights.py`（`--skip-index` フラグで Fan-in に対応）
- `frontend/scripts/generate-public-facts.mjs`
- `frontend/content/insights/weekly`（JSON ファイル + index.json）
- `frontend/content/facts/public`

### Workflows
- `.github/workflows/trigger-blog-cron.yml`（Daily Report、matrix max-parallel: 15）
- `.github/workflows/generate-weekly-insights.yml`（Weekly Report、Fan-in Matrix max-parallel: 10）
- `.github/workflows/retry-blog-draft-stores.yml`（Daily 失敗店舗再実行）
- `.github/workflows/generate-public-facts.yml`
- `.github/workflows/blog-ci.yml`
- `.github/workflows/notify-on-failure.yml`（GHA 失敗通知の再利用ワークフロー）

### Supabase
- `supabase/migrations/20260326000000_blog_drafts_content_split.sql`（content_type / is_published / edition / public_slug 追加）
