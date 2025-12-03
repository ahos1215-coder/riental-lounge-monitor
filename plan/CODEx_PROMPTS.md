# CODEX_PROMPTS

Guidance for using Codex (and similar assistants) on MEGRIBI.

## Core Facts to Tell the Model
- Source of truth: Supabase `logs`. Google Sheet/GAS is legacy fallback.
- `/api/range`: accepts `store` and `limit` only; no `from/to`. Supabase queried `ts.desc`, response sorted `ts.asc`. No backend time filter; frontend filters 19:00-05:00.
- `max_range_limit = 50000`; frontend typically uses 200-400.
- Frontend owns `computeNightWindow` and `isWithinNight` in `useStorePreviewData.ts`.
- Forecast APIs are gated by `ENABLE_FORECAST=1`.
- Architecture: Supabase -> Flask API -> Next.js 16 frontend.
- Cron: `/tasks/tick` every 5 minutes, collects 38 stores, writes to Supabase, refreshes forecasts when enabled.
- Store resolution: `?store=` overrides env default.
- Second-venue UX: frontend renders 4 Google Maps search links (darts/karaoke/ramen/love hotel); do not call Google Places API or change backend for this.

## Good Prompt Examples
- "Update `/api/range` handler to keep legacy fallback but skip any time filtering; Supabase newest-first, respond asc."
- "Add brand metadata to `stores` table while keeping store IDs stable; brands: Oriental / Aisekiya / JIS."
- "Ensure frontend night window (19:00-05:00) stays intact while adding a new series."
- "Keep second-venue feature as Google Maps search links; no Places API, no backend changes."

## Anti-Goals
- Do not reintroduce `from/to` parsing for standard `/api/range` calls.
- Do not add direct Supabase calls from the frontend.
- Do not expand legacy Google Sheet/GAS beyond parity fallback.
- Do not add Google Places API usage or change `/api/second_venues` for the map-link UX (frontend-only).
