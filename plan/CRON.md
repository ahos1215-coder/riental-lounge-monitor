# CRON
Last updated: YYYY-MM-DD / commit: TODO

## Production Schedule (Render backend)
- Job: `/tasks/multi_collect` (alias: `/api/tasks/collect_all_once`).
- Frequency: every 5 minutes.
- Scope: scrape ~38 stores via `multi_collect.collect_all_once`, insert into Supabase `logs` (src_brand=oriental), and optionally post to GAS when enabled. Weather is fetched once per prefecture and reused per store.
- Runtime: Render Starter tier (24h) is sufficient for 38 stores.
- Night collection: intended to run continuously across the night window (19:00–05:00) as long as cron is triggered.
- Legacy note: `/tasks/tick` is single-store + local/GAS-oriented and **does not insert into Supabase `logs`**; it remains for backward compatibility but is not the production cron target.

## Behavior
- `/tasks/multi_collect` calls `multi_collect.collect_all_once`:
  - Fetches current weather per prefecture once (when `ENABLE_WEATHER=1`) and reuses it for stores in the same region.
  - Scrapes men/women counts per store (total 38 entries), sleeping `BETWEEN_STORES_SEC` between stores.
  - Posts to GAS only when `ENABLE_GAS=1` and `GAS_URL`/`GAS_WEBHOOK_URL` is set.
  - Inserts each row into Supabase `public.logs` via REST using the service role key; includes weather fields when available.
- No server-side time windowing; timestamps come from Supabase inserts (night filtering is frontend-owned).
- Forecast updates are skipped when `ENABLE_FORECAST` is unset/0.
- `/tasks/tick` remains as a legacy single-store scraper for local/GAS usage; it writes to local storage + GAS, not Supabase `logs`.

## Monitoring
- Check server logs each run for success/failure.
- Validate data by hitting `/api/range?store=...&limit=400` to ensure latest rows exist (`ts.asc` response).

## Notes / Future
- Keep `DATA_BACKEND=supabase`; `/tasks/multi_collect` is the production path. Legacy `/tasks/tick` is intentionally unscheduled in production.
- Future: collectors stay Supabase-first; GAS posting remains optional.
- Do not throttle client-side; cron cadence is authoritative.
