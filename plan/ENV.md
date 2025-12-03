# ENV

Required and common environment variables for MEGRIBI.

## Backend
- `DATA_BACKEND` (default `supabase`): choose data source; legacy fallback exists.
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`: required for supabase mode.
- `MAX_RANGE_LIMIT` (default `50000`): hard cap for `/api/range`.
- `ENABLE_FORECAST` (`1` to enable forecasts, else disabled).
- `STORE_ID` (default store when query `?store` is absent).
- `TIMEZONE` (e.g., `Asia/Tokyo`): used for logging/labels; backend no longer uses it for `/api/range` filtering.

## Frontend
- Uses backend `/api/*`; no Supabase keys needed client-side.
- Store is chosen via query `?store=xxx`; env default is fallback.

## Cron / Collectors
- Same Supabase credentials as backend.
- Weather cache is handled internally; no extra env needed.
