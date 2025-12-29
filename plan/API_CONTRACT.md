# API_CONTRACT
Last updated: 2025-12-29 / commit: cf8c998

Authoritative contract for MEGRIBI backend endpoints. Keep existing behavior stable.

## Architecture / Data Sources
- Source of truth: Supabase `logs` (metrics) and `stores` (metadata).
- Google Sheet/GAS is legacy fallback only (do not expand).
- Frontend calls Flask via Next.js API routes (proxy). No direct Supabase access.
- Night window (19:00-05:00) filtering is frontend responsibility.

## Common Fields (Supabase logs)
`ts`, `store_id`, `src_brand`, `men`, `women`, `total`, `temp_c`, `precip_mm`, `weather_code`, `weather_label`

## GET /healthz
- Response: `{ ok: true, store, target, gs_webhook, gs_read, timezone, window, data_backend, supabase, http_timeout, http_retry, max_range_limit }`

## GET /api/meta
- Response: `{ ok: true, data: { store, store_id, data_backend, supabase, timezone, window, http_timeout, http_retry, max_range_limit } }`

## GET /api/current
- Query: `store` or `store_id` (optional)
- Behavior: return latest record for the store (legacy/local storage).
- Response: record object or `{}` when missing.

## GET /api/range
- Purpose: return raw log rows.
- Query (public contract):
  - `store` or `store_id`
  - `limit` (int, clamped to `MAX_RANGE_LIMIT`, default `min(500, MAX_RANGE_LIMIT)`)
- Behavior:
  - Supabase query uses `ts.desc` to fetch newest, response sorted `ts.asc`.
  - **Server-side time filtering is not part of the public contract.**
  - `from` / `to` exist for internal/debug only (do not rely on them externally).
- Response:
  - `{ ok: true, rows: [ { ts, men, women, total, store_id?, src_brand?, temp_c?, precip_mm?, weather_code?, weather_label? } ] }`

## GET /api/forecast_next_hour
- Query: `store` or `store_id`
- Behavior: enabled only when `ENABLE_FORECAST=1`, otherwise `503 { ok:false, error:"forecast-disabled" }`
- Response: `{ ok: true, data: [ { ts, men_pred, women_pred, total_pred } ] }`

## GET /api/forecast_today
- Query: `store` or `store_id`
- Behavior: enabled only when `ENABLE_FORECAST=1`, otherwise `503 { ok:false, error:"forecast-disabled" }`
- Response: `{ ok: true, data: [ { ts, men_pred, women_pred, total_pred } ] }`

## GET /api/second_venues
- Query: `store` or `store_id`
- Response: `{ ok: true, rows: [ { place_id, name, lat, lng, genre?, address?, open_now?, weekday_text?, updated_at? } ] }`
- If Supabase config is missing, returns `{ ok: true, rows: [] }`.

## Tasks / Cron
- `GET|POST /tasks/multi_collect` (alias `/api/tasks/collect_all_once`)
  - Response: `{ ok: true, task: "collect_all_once", stores: <count> }`
- `GET /tasks/tick`
  - Legacy single-store collection (local/GAS). Not the Supabase ingestion path.
- `GET|POST /tasks/update_second_venues`
  - Optional. Runs only when `GOOGLE_PLACES_API_KEY` is set.

## Frontend API Routes (Next.js proxy)
- `GET /api/range` → backend `/api/range` (query passthrough)
- `GET /api/forecast_today` → backend `/api/forecast_today`
- `GET /api/forecast_next_hour` → backend `/api/forecast_next_hour`
- `GET /api/second_venues` → backend `/api/second_venues`
