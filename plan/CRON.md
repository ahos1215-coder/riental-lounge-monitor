# CRON
Last updated: 2025-12-16 / commit: 8316d5a

## Policy（運用方針）
- 収集は **5分間隔** / **19:00-05:00** を想定（運用側の cron スケジュールで制御する）。
- 本番の収集入口は `GET /tasks/multi_collect`（alias: `GET /api/tasks/collect_all_once`）。
- `/tasks/tick` は **単店舗 + ローカル/GAS向けのレガシー**（本番 cron 対象にしない / Supabase `logs` insert ではない）。

## Cron Jobs（一覧）
| Job | Frequency | HTTP | Purpose |
|---|---:|---|---|
| collect_all_once | every 5 min（19:00-05:00） | `GET /tasks/multi_collect` | 38店舗を収集して Supabase `logs` に insert（必要なら GAS へ POST、天気は県単位キャッシュ） |
| collect_all_once（alias） | same | `GET /api/tasks/collect_all_once` | `/tasks/multi_collect` の alias |
| tick（legacy） | not scheduled | `GET /tasks/tick` | 単店舗を収集してローカル保存 + GAS append（夜窓外は skipped）。Supabase insert なし |
| update_second_venues（optional） | manual | `GET|POST /tasks/update_second_venues` | `GOOGLE_PLACES_API_KEY` がある場合のみ Supabase `second_venues` を更新（現行 UX は map-link が本流） |

## Behavior（コード準拠）
- `/tasks/multi_collect`（`oriental/routes/tasks.py`）
  - `multi_collect.collect_all_once()` を呼び、38店舗の men/women を収集する。
  - 店舗ごとに Supabase `public.logs` へ insert（service role key を使用）。
  - `ENABLE_GAS=1` かつ `GAS_URL`/`GAS_WEBHOOK_URL` がある場合、GAS にも POST する（legacy fallback）。
- `/tasks/tick`（legacy）
  - 夜窓外: `{ ok:true, skipped:true, reason:"outside-window", window:{start,end} }`
  - 実行: `{ ok:true, record, window }`（ローカル保存 + GAS append）

## Failure / Monitoring
- Render logs:
  - `collect_all_once.start/success/failed` を確認（`/tasks/multi_collect`）。
- Supabase:
  - `logs` テーブルに `store_id` ごとの新規行が増えていることを確認。
  - API 確認: `GET /api/range?store=<slug>&limit=400`（レスポンスは `ts.asc`）。
- Frontend:
  - 夜窓（19:00-05:00）の絞り込みはフロント責務。サーバ側に時間フィルタを追加しない。
