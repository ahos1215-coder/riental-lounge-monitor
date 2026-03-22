# INDEX（クイック参照）
Last updated: 2026-03-21  
Target commit: (see git)

**読む順・各ファイルの役割の一覧は [`README.md`](README.md) を正とする。**

---

## Repo Map（主要ディレクトリ）
- Backend（Flask）: `app.py`, `oriental/`
- Collector: `multi_collect.py`
- Frontend（Next.js 16）: `frontend/`
- Tests: `tests/`
- Scripts: `scripts/`
- Workflows: `.github/workflows/`
- Supabase migrations: `supabase/migrations/`

## Key Entry Points
### Backend
- `oriental/routes/data.py`（/api/range, /api/current）
- `oriental/routes/forecast.py`（/api/forecast_*）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick など）
- `oriental/data/provider.py`（Supabase logs）

### Frontend
- **LINE Webhook**: `frontend/src/app/api/line/route.ts`
- **インサイト**: `frontend/src/lib/blog/insightFromRange.ts`
- **Gemini 下書き**: `frontend/src/lib/blog/draftGenerator.ts`
- **LINE 意図解析**: `frontend/src/lib/line/parseLineIntent.ts`
- ページ: `frontend/src/app/page.tsx`, `stores/`, `store/[id]/`, `blog/`, `insights/weekly/`
- 店舗夜窓: `frontend/src/app/hooks/useStorePreviewData.ts`
- 二次会 map-link: `frontend/src/app/config/secondVenueMapLinks.ts`

### Content / Batch
- Weekly insights: `scripts/generate_weekly_insights.py` → `frontend/content/insights/weekly`
- Public facts: `frontend/scripts/generate-public-facts.mjs` → `frontend/content/facts/public`
- Blog MDX: `frontend/content/blog`

## Constraints（短縮版）
- Supabase `logs` が source of truth（Sheets/GAS は legacy fallback）
- `/api/range` は `store` + `limit` のみ（クエリ追加・サーバ側時間フィルタ禁止）
- **Flask は夜窓を採らない**。店舗 UI は `useStorePreviewData.ts`。**LINE 下書き**は `insightFromRange.ts`（取得済み JSON の集計）
- 二次会は map-link が本流
- **ブログ下書きに n8n は使わない**

用語: `GLOSSARY.md`
