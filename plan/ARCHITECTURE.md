# ARCHITECTURE
Last updated: 2025-12-29 / commit: fb524be

## High-Level Overview
- Stack: **Supabase → Flask API (Render) → Next.js 16 (Vercel)**.
- Data source priority: Supabase `logs` is primary. Google Sheet/GAS is legacy fallback only.
- Frontend uses Next.js API routes to proxy backend requests.

## Data Flow (Metrics)
1) `/tasks/multi_collect` collects ~38 stores and inserts into Supabase `logs`.
2) Flask reads Supabase via REST (`/rest/v1/logs`) using `requests` (`SupabaseLogsProvider`).
3) Frontend calls backend through Next.js API routes (`/api/range`, `/api/forecast_*`).
4) Night window (19:00-05:00) filtering is done in frontend (no server-side filtering).

## Forecast (Optional)
- `ENABLE_FORECAST=1` のとき `/api/forecast_today` / `/api/forecast_next_hour` が有効。
- 予測の履歴データも Supabase `logs` から取得する。

## Blog / Facts Pipeline
- Blog MDX: `frontend/content/blog/*.mdx`
- Public facts JSON: `frontend/content/facts/public/<facts_id>.json`
- `frontend/scripts/generate-public-facts.mjs` が blog frontmatter を読み、
  `/api/range` / `/api/forecast_today` を使って public facts を生成。
- `frontend/scripts/build-public-facts-index.mjs` が `index.json` を生成。
- Public facts はリポジトリに commit する。フル版 facts は repo に保存しない。

## Responsibility Split
- Night window filtering: frontend only (`useStorePreviewData.ts` / facts生成スクリプト)。
- Draft preview gate: `BLOG_PREVIEW_TOKEN` 一致時のみ表示/metadata 生成。
- Secrets: 環境変数のみ。`NEXT_PUBLIC_*` に秘密値禁止。

## Second Venues
- UI は map-link 方針（Google Maps 検索リンクを生成）。
- Backend `/api/second_venues` は互換/将来用として残置。

## Legacy
- `/tasks/tick` は legacy（単店/ローカル/GAS向け）。主経路は `/tasks/multi_collect`。
