# ARCHITECTURE
Last updated: 2026-03-21
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores) -> Flask API (Render) -> Next.js 16 (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- Night window（19:00–05:00）: **店舗 UI** は `useStorePreviewData.ts`。**LINE 下書き**は同じ窓定義を **`insightFromRange.ts`**（Next サーバー）で適用。Flask は夜窓を採らない。
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は GitHub Actions で生成し、`frontend/content/*` にコミット
- LINE からのブログ下書き: Next.js `POST /api/line` が Webhook を受信し、`BACKEND_URL` 経由で `/api/range` と `/api/forecast_today` を取得し、**`insightFromRange.ts`** でインサイト化 → Gemini で MDX 下書き → Supabase `blog_drafts`。**n8n は使わない。**

## Data Flow
1) 収集: `multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む
   - `/tasks/tick` はレガシー（単店 + ローカル保存）
2) Flask API が `/api/range` / `/api/current` / `/api/forecast_*` を提供
   - `/api/current` はローカル保存（`data.json`）の最新値
   - `/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却
3) Next.js は API routes を介して backend を呼ぶ
   - 店舗 UI の夜窓は `useStorePreviewData.ts`。LINE 下書きは `insightFromRange.ts`（いずれも **Flask `/api/range` の契約は不変**）
4) GitHub Actions が Insights / Facts を生成し静的 JSON を更新
   - `/insights/weekly` 系ページは fs から読み込む
5) LINE → `POST /api/line` → 下書きを `blog_drafts` に保存（閲覧・公開フローは `BLOG_CONTENT.md` 参照）

## Contracts / Constraints
- `/api/range` の公開契約は `store` + `limit` のみ
  - server-side の時間フィルタ禁止。night window は **店舗 UI のフロント**および **LINE 用 `insightFromRange.ts`** で、取得済み行に対して実施
- Secrets は環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）
- 既存エンドポイント互換性を維持（/healthz, /api/meta, /api/current, /api/range, /api/forecast_*, /tasks/*）
- Second venues は map-link 方式を維持（Places API 依存に戻さない）

## Blog Cron Scale Strategy (39 stores)
- 現行 `/api/cron/blog-draft` は `duration_ms` / `near_timeout` / `results[].duration_ms` を返し、1回の実行時間を計測できる。
- しきい値の目安: `near_timeout=true`（約50秒超）または Vercel 側で 504 が見えたら分割実行へ移行。
- 分割案（推奨順）:
  1) **GitHub Actions で店舗シャーディング**: 店舗CSVを複数バッチに分割して `edition` 固定で複数回叩く。
  2) **並列数制限つき実行**: matrix `max-parallel` で同時呼び出しを制御（API負荷とX/Gemini制限を両立）。
  3) **後段キュー**: 必要時のみ（複雑化コストが高いため最終手段）。
- SNS 自動投稿のリトライ方針（Free/Basic想定）:
  - 429/5xx のみ再試行、`2s -> 5s -> 10s` の指数寄りバックオフ
  - 日次上限に近い場合は投稿スキップして翌便へ繰り越し（失敗扱いにしない）

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
- `frontend/src/lib/blog/insightFromRange.ts`（LINE 用インサイト・窓計算）
- `frontend/src/lib/blog/draftGenerator.ts`（Gemini 下書き）
- `frontend/src/app/hooks/useStorePreviewData.ts`（店舗 UI 夜窓）
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
