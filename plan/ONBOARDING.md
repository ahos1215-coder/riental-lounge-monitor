# ONBOARDING

Welcome to MEGRIBI. This document is the single source for how to get productive quickly.

## What We Are Building
- Data flow: **Supabase logs (source of truth) -> Flask API -> Next.js 16 frontend**.
- Legacy Google Sheet/GAS exists only as a fallback path; do not extend it.
- Night view: UI shows a single night window 19:00-05:00 local time. The frontend filters; the backend does not time-filter.

## Core Specs You Must Know
- `/api/range`: accepts `store` and `limit` only. No `from/to`. Backend returns up to `limit` rows ordered by `ts` ascending; Supabase is queried newest-first and resorted before returning. `max_range_limit = 50000`.
- Forecast APIs (e.g., `/api/forecast_today`) are active only when `ENABLE_FORECAST=1`.
- Store resolution: query `?store=xxx` wins; env default is the fallback store.
- Multi-brand (Oriental / Aisekiya / JIS) is coming via a `stores` table; design forward-compatible identifiers.

## Local Setup (Backend)
```sh
python -m venv .venv
. .venv/Scripts/activate  # Windows
pip install -r requirements.txt
set DATA_BACKEND=supabase
python app.py
```

## Local Setup (Frontend)
```sh
cd frontend
npm install
npm run dev
```
- The frontend calls the Flask backend `/api/*` endpoints; no direct Supabase calls from the browser.
- `useStorePreviewData.ts` owns `computeNightWindow` and `isWithinNight` to filter to 19:00-05:00.

## Daily Flow
- Start backend (`python app.py`) and frontend (`npm run dev`), then open `http://localhost:3000/?store=nagasaki`.
- Use `curl http://127.0.0.1:5000/api/range?store=nagasaki&limit=400` to inspect raw rows.

## Key Files
- Backend: `oriental/data/provider.py`, `oriental/routes/data.py`, `oriental/config.py`.
- Frontend: `frontend/src/app/hooks/useStorePreviewData.ts`.
- Cron collector: `multi_collect.py` (writes directly into Supabase; weather cached per prefecture).

## Support Channels
- If unsure about API behavior, re-read `API_CONTRACT.md`.
- If adding stores/brands, reflect them in Supabase `stores` and keep the default env store as fallback.
