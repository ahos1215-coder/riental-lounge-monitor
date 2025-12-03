# ROADMAP

## Now (Stabilize)
- Guarantee `/api/range` returns latest data: Supabase queried `ts.desc`, then responses returned `ts.asc`.
- Keep `DATA_BACKEND=supabase` as default; legacy path is fallback only.
- Enforce `max_range_limit = 50000`; frontend should use `limit` 200-400.
- Ensure `useStorePreviewData` night filtering (19:00-05:00) remains intact.
- Second-venue UX is now Google Maps search links (darts/karaoke/ramen/love hotel); legacy Google Places/NearbySearch path is paused and only considered for future NLP experiments.

## Next (Q1)
- Introduce multi-brand support via `stores` table (Oriental / Aisekiya / JIS) with routing/display metadata.
- Harden forecast toggling: respect `ENABLE_FORECAST=1` and degrade gracefully when disabled.
- Improve observability for `/tasks/tick` cron: per-run success/fail metrics every 5 minutes.

## Later
- Weather cache governance and eviction per prefecture.
- Per-store retention/archival policy in Supabase logs.
- Backfill tooling to re-push historical nights when schemas change.

## Nice-to-haves
- Admin UI to inspect raw Supabase logs and cron status.
- E2E smoke that the frontend renders a full 19:00-05:00 night for a chosen store.
