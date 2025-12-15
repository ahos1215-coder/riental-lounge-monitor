# API_CONTRACT
Last updated: YYYY-MM-DD / commit: TODO

Authoritative contract for MEGRIBI backend endpoints. Keep existing behavior stable; do not introduce breaking changes.

## Architecture / Data Sources
- Source of truth: Supabase `logs` (metrics) and `stores` (metadata). Google Sheet/GAS is legacy fallback only.
- Stack: Supabase → Flask API (Render) → Next.js 16 frontend (Vercel). Frontend calls API Routes; no direct Supabase access.
- Night window判定 (19:00–05:00) はフロント専任（`useStorePreviewData.ts` など）。サーバー側で時間フィルタを入れない。
- `max_range_limit = 50000`（リクエストをクランプ）。フロント推奨 `limit` は 200–400。
- 空データでも `{ ok: true, data: [] }` または `{ ok: true, rows: [] }` を返す。

## GET /api/current
- Purpose: latest snapshot for a store.
- Query:
  - `store` (or `store_id`): store identifier. Overrides env default.
- Behavior: Fetch the newest row for the store from Supabase (`logs`). No time filtering beyond “latest”.
- Response: `{ ok: true, data: { ts, men, women, total, store_id?, weather_code?, weather_label?, temp_c?, precip_mm?, src_brand? } }`

## GET /api/range
- Purpose: return raw log rows.
- Query:
  - `store` (or `store_id`): store identifier.
  - `limit` (int): number of rows to return; clamped to `max_range_limit = 50000`. Frontend推奨 200–400。
- Behavior:
  - Supabase query ordered `ts.desc` to fetch newest rows, then response sorted `ts.asc`.
  - **Server-side時間フィルタ禁止**（from/to なし、夜間フィルタなし）。夜ウィンドウ判定はフロントで実施。
- Response: `{ ok: true, rows: [ { ts, men, women, total, store_id?, weather_code?, weather_label?, temp_c?, precip_mm?, src_brand? } ] }`

## GET /api/forecast_next_hour
- Purpose: short-horizon forecast for the next ~hour.
- Query: `store`.
- Behavior: Enabled only when `ENABLE_FORECAST=1`; otherwise may return empty data with `ok: true`.
- Response: `{ ok: true, data: [ { ts, men, women, total } ] }` (empty array permitted).

## GET /api/forecast_today
- Purpose: forecast points for the current night window.
- Query: `store`.
- Behavior: Enabled only when `ENABLE_FORECAST=1`; otherwise returns `{ ok: true, data: [] }`.
- Response: `{ ok: true, data: [ { ts, men, women, total } ] }` (empty array permitted).

## Other endpoints (stable, minimal)
- `/api/meta`: returns config summary.
- `/api/heatmap`, `/api/range_prevweek`, `/api/summary`, `/api/stores/list`: placeholders / minimal responses; keep contracts unchanged.
- `/tasks/tick`: cron entry point (every 5 minutes in production) that collects ~38 stores, writes to Supabase, and refreshes forecasts when enabled.

## Second Venues (legacy note)
- Current production UX is **frontend map-link only** (Google Maps search links). No backend/Supabase usage for second venues.
- `/api/second_venues` is retained for future lightweight recommendations; keep existing behavior stable but do not expand without explicit direction.

## Legacy GAS/Google Sheet path (fallback-only)
- Legacy path may still exist as a fallback. Do not expand its scope beyond parity; Supabase is the primary data source.

