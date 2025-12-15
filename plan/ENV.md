# ENV
Last updated: YYYY-MM-DD / commit: TODO

Required and common environment variables for MEGRIBI.

## Backend (Render / Flask)
- `DATA_BACKEND` (default `supabase`): primary source is Supabase; legacy fallback exists but not default.
- `BACKEND_URL`: base URL used by Vercel frontend to reach the Render backend.
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (server-side only; never expose to frontend)
- `MAX_RANGE_LIMIT` (default `50000`): hard cap for `/api/range`.
- `ENABLE_FORECAST` (`1` to enable forecasts; unset/0 to disable gracefully).
- `STORE_ID` (default store when query `?store` is absent).
- `TIMEZONE` (e.g., `Asia/Tokyo`): for logging/labels; backend must not use it for `/api/range` filtering.

## Frontend (Vercel / Next.js 16)
- Calls backend `/api/*` via `BACKEND_URL`; no direct Supabase access.
- Store selection via query `?store=xxx`; backend env default is fallback.
- Google Places API key: **not used** (second venues are map-link only).

## Cron / Collectors
- Use the same Supabase credentials as backend.
- `ENABLE_FORECAST` toggles forecast refresh in `/tasks/tick`.
- Weather cache handled internally; no extra env required.

