# API_CONTRACT

Authoritative contract for MEGRIBI backend endpoints.

## General
- Data source: Supabase `logs` table (source of truth).
- Legacy Google Sheet/GAS path exists only as fallback.
- Store resolution: query `?store=xxx` (or `store_id`) overrides env default.
- `max_range_limit = 50000`; requests are clamped to this.

## GET /api/range
- Purpose: return raw log rows.
- Query params:
  - `store` (or `store_id`): store identifier.
  - `limit` (int): number of rows to return. Recommended 200-400; capped at 50000.
- Behavior:
  - Backend does **not** apply date/time filters when `from/to` are absent (standard flow).
  - Supabase is queried `ts.desc` to fetch newest rows; response is sorted `ts.asc`.
  - Fields: `ts`, `men`, `women`, `total`, plus optional `store_id`, `weather_code`, `weather_label`, `temp_c`, `precip_mm`, `src_brand`.
- Response:
```json
{ "ok": true, "rows": [ { "ts": "2025-11-28T10:00:00Z", "men": 3, "women": 5, "total": 8 } ] }
```

## GET /api/forecast_today
- Enabled only when `ENABLE_FORECAST=1`.
- Query params: `store`.
- Response: `{ "ok": true, "data": [...] }` with forecast points for the current night; may be empty when disabled.

## Other endpoints
- `/api/current`: latest snapshot from storage.
- `/api/meta`: returns config summary.
- `/api/heatmap`, `/api/range_prevweek`, `/api/summary`, `/api/stores/list`: placeholders; keep contract stable but minimal.
- `/api/second_venues`: legacy/experimental; frontend now uses Google Maps search-link UI instead. Keep behavior stable but do not extend unless a future migration is planned.

## Frontend Expectations
- Frontend (Next.js) calls these endpoints; no direct Supabase access.
- Night window filtering (19:00-05:00) is entirely frontend: `computeNightWindow` and `isWithinNight` in `useStorePreviewData.ts`.
