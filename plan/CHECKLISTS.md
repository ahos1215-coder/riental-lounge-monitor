# CHECKLISTS

## Pre-Deploy
- [ ] `DATA_BACKEND=supabase` configured; Supabase URL/key present.
- [ ] `max_range_limit` set to `50000`.
- [ ] `ENABLE_FORECAST` set appropriately (1 to enable, empty/0 to disable gracefully).
- [ ] `/api/range?store=...&limit=400` returns newest rows (ts asc).
- [ ] Frontend builds (`npm run build`) and night filtering verified.

## Debugging Missing Data
- [ ] Call `/api/range?store=...&limit=400`; confirm latest night rows exist.
- [ ] Inspect `/tasks/tick` logs for the last run.
- [ ] Validate Supabase insert path in `multi_collect.py`.
- [ ] Confirm `?store` query matches expected store; env default otherwise.

## Forecast Issues
- [ ] Check `ENABLE_FORECAST=1`.
- [ ] Confirm cron ran within last 5 minutes.
- [ ] Frontend still renders actuals; note gap is expected when disabled.

## Backup
- [ ] Stop services.
- [ ] Create ZIP per RUNBOOK instructions.
- [ ] Store off-box.
