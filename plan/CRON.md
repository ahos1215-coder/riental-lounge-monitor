# CRON

## Production Schedule
- Job: `/tasks/tick`
- Frequency: every 5 minutes.
- Scope: collect logs for 38 stores and refresh forecasts (when `ENABLE_FORECAST=1`).
- Backend: Flask route, writes directly to Supabase `logs`; weather is cached per prefecture.

## Behavior
- Uses `multi_collect.py` to batch fetch and insert into Supabase.
- No server-side time windowing; relies on Supabase timestamps.
- Forecast updates are skipped when `ENABLE_FORECAST` is unset/0.

## Monitoring
- Check server logs each run for success/failure.
- Validate data by hitting `/api/range?store=...&limit=400` to ensure latest rows exist.

## Notes
- Keep `DATA_BACKEND=supabase`; legacy collection paths are not scheduled.
- Do not throttle client-side; cron cadence is authoritative.
