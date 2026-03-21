# ARCHITECTURE
Last updated: 2026-03-21
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores) -> Flask API (Render) -> Next.js 16 (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- Night window（19:00–05:00）はフロント責務（`frontend/src/app/hooks/useStorePreviewData.ts`）
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は GitHub Actions で生成し、`frontend/content/*` にコミット
- LINE からのブログ下書き: Next.js `POST /api/line` が Webhook を受信し、`BACKEND_URL` 経由で `/api/range` と `/api/forecast_today` を取得し、夜窓 insight を計算したうえで Gemini により MDX 下書きを生成。Supabase `blog_drafts` に保存（server-only・service role）。

## Data Flow
1) 収集: `multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む
   - `/tasks/tick` はレガシー（単店 + ローカル保存）
2) Flask API が `/api/range` / `/api/current` / `/api/forecast_*` を提供
   - `/api/current` はローカル保存（`data.json`）の最新値
   - `/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却
3) Next.js は API routes を介して backend を呼ぶ
   - 夜窓の判定・絞り込みはフロント側で実施
4) GitHub Actions が Insights / Facts を生成し静的 JSON を更新
   - `/insights/weekly` 系ページは fs から読み込む
5) （任意）LINE → `POST /api/line` → 下書きを `blog_drafts` に保存（閲覧ページは未接続の場合あり）

## Contracts / Constraints
- `/api/range` の公開契約は `store` + `limit` のみ
  - server-side の時間フィルタ禁止、night window はフロント責務
- Secrets は環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）
- 既存エンドポイント互換性を維持（/healthz, /api/meta, /api/current, /api/range, /api/forecast_*, /tasks/*）
- Second venues は map-link 方式を維持（Places API 依存に戻さない）

## Key Files
### Backend
- `oriental/routes/data.py`（/api/range, /api/current）
- `oriental/routes/forecast.py`（/api/forecast_*）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick など）
- `oriental/data/provider.py`（Supabase logs provider）
- `multi_collect.py`（収集ロジック）

### Frontend
- `frontend/src/app/api/*/route.ts`（backend proxy）
- `frontend/src/app/api/line/route.ts`（LINE Messaging webhook → 下書き生成）
- `frontend/src/app/hooks/useStorePreviewData.ts`（夜窓ロジック）
- `frontend/src/app/insights/weekly/**`（週次インサイトページ）
- `frontend/src/app/blog/**`（ブログ）
- `frontend/src/app/store/[id]/page.tsx`（店舗詳細）

### Content / Batch
- `scripts/generate_weekly_insights.py`
- `frontend/scripts/generate-public-facts.mjs`
- `frontend/content/insights/weekly`
- `frontend/content/facts/public`

### Workflows
- `.github/workflows/generate-weekly-insights.yml`
- `.github/workflows/generate-public-facts.yml`
- `.github/workflows/blog-ci.yml`
