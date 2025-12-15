# CHECKLISTS
Last updated: YYYY-MM-DD / commit: TODO

## Pre-Deploy (Render backend / Vercel frontend)
- [ ] Backend (Render/Flask) env: `DATA_BACKEND=supabase`, Supabase URL/anon key set via env (no hardcode), `max_range_limit=50000`.
- [ ] RLS off for `logs`/`stores` (or service role key used appropriately); tables exist as expected.
- [ ] `ENABLE_FORECAST` set (1 to enable; empty/0 to disable gracefully).
- [ ] `/api/range?store=...&limit=400` returns newest rows, response `ts.asc`; no server-side time filter.
- [ ] Frontend (Vercel/Next.js 16) build passes (`npm run build`), with `useSearchParams` components under `Suspense`.
- [ ] Recharts Tooltip: custom type extends `TooltipProps` to add `label`/`payload` (avoid TS build errors).
- [ ] Second venues: map-link UI renders Google Maps search buttons (no backend dependency).
- [ ] Supabase secrets/API keys stored in env; not committed.

## Debugging Missing Data
- [ ] Call `/api/range?store=...&limit=400`; confirm latest night rows exist and sorted asc.
- [ ] Inspect `/tasks/tick` logs (last run, success/fail) on Render.
- [ ] Validate Supabase insert path in `multi_collect.py` and network connectivity.
- [ ] Confirm `?store` query matches expected store; env default otherwise.

## Forecast Issues
- [ ] `ENABLE_FORECAST=1` and cron ran within last 5 minutes.
- [ ] If disabled, frontend should still render actuals; empty forecast array is acceptable.

## Frontend Specific (Next.js 16)
- [ ] `useSearchParams` / `useRouter` used only under `Suspense`.
- [ ] Recharts TooltipProps extended with custom type (`label?: string | number; payload?: any[]`).
- [ ] Night window filtering (19:00–05:00) handled client-side (`useStorePreviewData.ts`); server keeps full range.
- [ ] Second venues map-link buttons open Google Maps searches for nearby categories.
- [ ] DNSキャッシュ注意: 反映確認は Shift+F5 または DevTools Network → Disable Cache を有効化。

## Backup
- [ ] Stop services if needed.
- [ ] Create ZIP per RUNBOOK instructions.
- [ ] Store off-box securely.
