# INDEX
Last updated: 2025-12-29 / commit: 4299ff1

このファイルは「全体の地図」「読む順番」「重要ファイル一覧」をまとめる入口です。

## Read Order (Start Here)
1) `README.md`
2) `plan/STATUS.md`
3) `plan/DECISIONS.md`
4) `plan/API_CONTRACT.md`
5) `plan/ARCHITECTURE.md`
6) `plan/RUNBOOK.md`
7) `plan/ENV.md`
8) `plan/CRON.md`
9) `plan/SECOND_VENUES.md`
10) `plan/ROADMAP.md`
11) `plan/CODEx_PROMPTS.md`

補助: `plan/repo_map.txt` がある場合は先に見る。

## Repo Map (主要ディレクトリ)
- Backend (Flask): `app.py`, `wsgi.py`, `oriental/`
- Collector: `multi_collect.py` (`/tasks/multi_collect` から呼ばれる)
- Frontend (Next.js 16): `frontend/`
  - API routes: `frontend/src/app/api/*/route.ts`
  - Blog: `frontend/content/blog/*.mdx`
  - Public facts: `frontend/content/facts/public/*.json`
  - Scripts: `frontend/scripts/*.mjs`
- Specs: `plan/`

## Key Entry Points
- Backend routes: `oriental/routes/data.py`, `oriental/routes/forecast.py`, `oriental/routes/tasks.py`
- Supabase provider: `oriental/data/provider.py` (`/rest/v1/logs`)
- Night window: `frontend/src/app/hooks/useStorePreviewData.ts`
- Blog page: `frontend/src/app/blog/[slug]/page.tsx` (draft/preview gate)
- Facts generation: `frontend/scripts/generate-public-facts.mjs`
- Facts index: `frontend/scripts/build-public-facts-index.mjs`

## Blog / Facts (契約・運用)
- request schema: `plan/BLOG_REQUEST_SCHEMA.md`
- pipeline: `plan/BLOG_PIPELINE.md`
- content policy: `plan/BLOG_CONTENT.md`

## Constraints (短縮版)
- Supabase `logs` が source of truth（Sheets/GAS は legacy fallback）。
- `/api/range` は `store` + `limit` のみ（サーバ側時間フィルタ禁止）。
- 夜窓(19:00-05:00)の絞り込みはフロント責務。
- Second venues は map-link 方針（Places API 収集・保存型に戻さない）。
