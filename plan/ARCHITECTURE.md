# ARCHITECTURE

## High-Level
- Three layers: **Supabase logs (source of truth) -> Flask API -> Next.js 16 frontend**.
- Forecasting is optional (`ENABLE_FORECAST=1`); falls back to actuals-only when disabled.
- Legacy Google Sheet/GAS path remains only as a fallback.

## Data Flow
1. Collectors (`multi_collect.py`, `/tasks/tick`) write directly to Supabase `logs`; weather cached per prefecture.
2. Flask serves `/api/range` and `/api/forecast_today`, reading from Supabase by default (`DATA_BACKEND=supabase`).
3. Frontend calls `/api/*` via the backend, then filters to the night window (19:00-05:00) client-side.

## Key Components
- `oriental/data/provider.py`: Supabase client (newest-first fetch, returns asc).
- `oriental/routes/data.py`: `/api/range` contract enforcement; no server-side time filter.
- `frontend/src/app/hooks/useStorePreviewData.ts`: `computeNightWindow` and `isWithinNight`.
- `multi_collect.py`: batch ingestion plus forecast refresh; caches weather.

## Store Resolution
- Query `?store=xxx` (or `store_id`) is authoritative; env default store is fallback.
- Multi-brand support (Oriental / Aisekiya / JIS) planned via `stores` table; design IDs and metadata to be brand-aware.

## Constraints
- `max_range_limit = 50000`; frontend should request 200-400 rows.
- Backend must not reintroduce `from/to` filtering in standard flows; UI owns night filtering.
