# INDEX
Last updated: 2025-12-23
Target commit: 10e50d6

このファイルは「全体の地図」「読む順番」「重要ファイル一覧」をまとめる入口です。

## Read Order（Start Here）
1) `plan/CODEx_PROMPTS.md`（AI の作業ルール）
2) `plan/STATUS.md`（現状の稼働状況）
3) `plan/DECISIONS.md`（壊してはいけない判断）
4) `plan/API_CONTRACT.md`（API 契約）
5) `plan/ARCHITECTURE.md`（全体アーキテクチャ）
6) `plan/RUNBOOK.md`（起動 / 運用）
7) `plan/CRON.md`（定期処理）
8) `plan/ENV.md`（環境変数）
9) `plan/SECOND_VENUES.md`（二次会スポット方針）
10) `plan/ROADMAP.md`（今後の計画）

## Repo Map（主要ディレクトリ）
- Backend（Flask）: `app.py`, `oriental/`
- Collector: `multi_collect.py`
- Frontend（Next.js 16）: `frontend/`
- Tests: `tests/`
- Scripts: `scripts/`
- Workflows: `.github/workflows/`

## Key Entry Points
### Backend
- `oriental/routes/data.py`（/api/range, /api/current）
- `oriental/routes/forecast.py`（/api/forecast_*）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick など）
- `oriental/data/provider.py`（Supabase logs）

### Frontend
- `/`: `frontend/src/app/page.tsx`
- `/stores`: `frontend/src/app/stores/page.tsx`
- `/store/[id]`: `frontend/src/app/store/[id]/page.tsx`
- `/blog`: `frontend/src/app/blog/page.tsx`
- `/blog/[slug]`: `frontend/src/app/blog/[slug]/page.tsx`
- `/insights/weekly`: `frontend/src/app/insights/weekly/page.tsx`
- `/insights/weekly/[store]`: `frontend/src/app/insights/weekly/[store]/page.tsx`
- Night window: `frontend/src/app/hooks/useStorePreviewData.ts`
- Second venues (map-link): `frontend/src/app/config/secondVenueMapLinks.ts`

### Content / Batch
- Weekly insights generator: `scripts/generate_weekly_insights.py`
- Public facts generator: `frontend/scripts/generate-public-facts.mjs`
- Insights data: `frontend/content/insights/weekly`
- Facts data: `frontend/content/facts/public`
- Blog content: `frontend/content/blog`

## Constraints（短縮版）
- Supabase `logs` が source of truth（Sheets/GAS は legacy fallback）
- `/api/range` は `store` + `limit` のみ（クエリ追加・サーバ側時間フィルタ禁止）
- 夜窓（19:00–05:00）の絞り込みはフロント専任
- 二次会スポットは map-link が本流（Places API 依存に戻さない）
