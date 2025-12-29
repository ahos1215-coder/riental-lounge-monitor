# INDEX
Last updated: 2025-12-17 / commit: d4538a0

このファイルは「全体の地図」「読む順番」「重要ファイル一覧」を 1ページでまとめるための入口です。

## Read Order（Start Here）
1) `plan/STATUS.md`（現状の稼働状況 / 今動いている機能）
2) `plan/DECISIONS.md`（壊してはいけない設計判断）
3) `plan/API_CONTRACT.md`（API 契約）
4) `plan/ARCHITECTURE.md`（全体アーキテクチャ / データフロー）
5) `plan/RUNBOOK.md`（ローカル起動 / 疎通 / よくある詰まり）
6) `plan/CRON.md` / `plan/ENV.md`（運用スケジュール / env の置き場所）
7) `plan/SECOND_VENUES.md`（二次会スポット: map-link 方針）
8) `plan/CODEx_PROMPTS.md`（AI 向けの作業ルール・出力フォーマット）

補助: `plan/repo_map.txt` がある場合は、先に見て探索コストを下げる。

## Repo Map（主要ディレクトリ）
- Backend（Flask）: `app.py`, `oriental/`
- Collector（収集スクリプト）: `multi_collect.py`（`/tasks/multi_collect` から呼ばれる）
- Frontend（Next.js 16）: `frontend/`
- Tests: `tests/`

## Key Entry Points（よく触る場所）
- Backend routes: `oriental/routes/*.py`
  - tasks/収集: `oriental/routes/tasks.py`（`/tasks/multi_collect`, `/tasks/tick`）
  - data/API: `oriental/routes/data.py`（`/api/range` など）
- Supabase provider: `oriental/data/provider.py`（`/api/range` の取得。`ts.desc` → `ts.asc`）
- Store IDs: `oriental/utils/stores.py`, `multi_collect.py`, `frontend/src/app/config/stores.ts`
- Frontend pages（App Router）:
  - `/`: `frontend/src/app/page.tsx`
  - `/stores`: `frontend/src/app/stores/page.tsx`
  - `/store/[id]`: `frontend/src/app/store/[id]/page.tsx`（`params.id`=slug + `?store=slug` 前提）
- Night window（19:00-05:00）: `frontend/src/app/hooks/useStorePreviewData.ts`（サーバへ移さない）
- Second venues（map-link）:
  - config: `frontend/src/app/config/secondVenueMapLinks.ts`
  - UI: `frontend/src/components/SecondVenuesList.tsx`
- Blog / Facts（契約・運用）:
  - request schema: `plan/BLOG_REQUEST_SCHEMA.md`
  - pipeline: `plan/BLOG_PIPELINE.md`
  - content policy: `plan/BLOG_CONTENT.md`

## Constraints（短縮版）
- Supabase `logs` が source of truth（Sheets/GAS は legacy fallback、拡張禁止）。
- `/api/range` は `store` + `limit` のみ（クエリ追加・サーバ側時間フィルタ禁止）。
- 夜窓（19:00-05:00）の絞り込みはフロント専任（`useStorePreviewData.ts`）。
- 二次会スポットは map-link が本流（Places API 収集・保存を必須にしない）。
