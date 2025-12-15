# ARCHITECTURE
Last updated: YYYY-MM-DD / commit: TODO

## High-Level Overview
- Stack: **Supabase (logs/stores, source of truth) → Flask API (Render Starter, 24h常時起動) → Next.js 16 frontend (Vercel)**.
- Data source priority: Supabase is primary; Google Sheet/GAS is legacy fallback only (do not expand).
- Second venues: **map-link frontend only** (Google Maps search links). Google Places API/Supabase保存は現状使わない。
- Forecasting is optional (`ENABLE_FORECAST=1`); when disabled, frontend shows actuals only.

## Data Flow
1) Collectors (`multi_collect.py`, `/tasks/tick`) run every 5 minutes, fetch ~38 stores, and write to Supabase `logs` (weather cached per prefecture).  
2) Flask API serves `/api/range`, `/api/current`, `/api/forecast_next_hour`, `/api/forecast_today`, reading from Supabase by default (`DATA_BACKEND=supabase`).  
3) Frontend (Next.js 16 on Vercel) calls the Flask API via API Routes; it owns night-window filtering (19:00–05:00) client-side.  
4) Responses remain `{ ok: true, rows/data: [...] }` even when empty.

## Key Contracts / Constraints
- `/api/range`: query only `store` + `limit`; Supabase `ts.desc` fetch → response `ts.asc`. **Server-side時間フィルタ禁止**（from/to や夜間絞り込みなし）。Night window判定は `useStorePreviewData.ts` で実施。
- `max_range_limit = 50000`; frontend推奨 200–400。
- Store resolution: `?store=` (or `store_id`) overrides env default.
- Keep core endpoints stable: `/healthz`, `/api/meta`, `/api/current`, `/api/range`, `/api/forecast_*`, `/tasks/tick`.
- No hardcoded secrets; use environment variables.

## Components / Files of Interest
- Backend: `oriental/data/provider.py` (Supabase client, newest-first fetch, returns asc), `oriental/routes/data.py` (`/api/range` contract enforcement).
- Frontend: `frontend/src/app/hooks/useStorePreviewData.ts` (night window helpers), `frontend/src/app/page.tsx` (Suspense wrapping for `useSearchParams`), `frontend/src/components/PreviewMainSection.tsx` (Recharts Tooltip型拡張).
- Ingestion: `multi_collect.py` and `/tasks/tick` (cron entrypoint, forecast refresh when enabled).

## Legacy Notes
- GAS/Google Sheet path exists only as fallback; do not extend beyond parity.
- `/api/second_venues` retained for future lightweight recommendations; production UX is map-link only.

