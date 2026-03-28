# API_CONTRACT
Last updated: 2026-03-29 (Round 8 整合: ML 3.0 / schema v2)
Target commit: (see git)

MEGRIBI の公開契約。**Flask（Render）** と **Next.js（Vercel）の LINE Webhook** を含む。互換性を壊さないこと。

## Global rules
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）。
- レイヤ構造: Supabase → Flask → Next.js（frontend は Next API routes 経由で backend を呼ぶ）。
- `/api/range` の公開契約は **`store` / `limit` のみ**。サーバ側の時間フィルタは追加しない。
- Night window（19:00–05:00）: **店舗 UI** はフロント（`useStorePreviewData.ts`）。**LINE 下書き**は **`insightFromRange.ts`** で取得済み行に対して集計。Flask は夜窓を採らない。
- `MAX_RANGE_LIMIT` で `limit` を clamp（未指定時は `min(500, MAX_RANGE_LIMIT)`）。

## Next.js (Vercel) — LINE Webhook

### GET /api/line
- ヘルスチェック用。
- Response（例）: `{ "ok": true, "service": "line-webhook" }`

### POST /api/line
- LINE Messaging API の Webhook（`Content-Type: application/json`）。
- 本番では `x-line-signature` と `LINE_CHANNEL_SECRET` による署名検証（**development のみ** `SKIP_LINE_SIGNATURE_VERIFY=1` でスキップ可。`plan/ENV.md`）。
- 処理内容（高レベル）: イベント解析 → `BACKEND_URL` 経由で Flask `GET /api/range`（および必要なら `GET /api/forecast_today`）→ インサイト → Gemini 下書き → Supabase `blog_drafts` → LINE 返信。
- **Flask の `/api/range` 契約は変更しない**（追加クエリを付けない）。窓・集計は Next アプリ層（`insightFromRange.ts`）。
- ブログ配管に **n8n は使わない**。

## Responses（共通）
- 成功時は `{ ok: true, ... }` を返す。
- 返却データが空でも空配列/空オブジェクトで返す（例: `{ ok: true, rows: [] }`）。

## GET /healthz
稼働確認と設定サマリ。

Response (例)
```json
{
  "ok": true,
  "store": "...",
  "target": true,
  "gs_webhook": false,
  "gs_read": false,
  "timezone": "...",
  "window": { "start": 19, "end": 5 },
  "data_backend": "supabase",
  "supabase": { "url": true, "service_role": true, "store_id": "..." },
  "http_timeout": 12,
  "http_retry": 3,
  "max_range_limit": 50000
}
```

## GET /api/meta
設定サマリ。

Response (例)
```json
{
  "ok": true,
  "data": {
    "store": "...",
    "store_id": "...",
    "data_backend": "supabase",
    "supabase": { "url": true, "service_role": true, "store_id": "..." },
    "timezone": "...",
    "window": { "start": 19, "end": 5 },
    "http_timeout": 12,
    "http_retry": 3,
    "max_range_limit": 50000
  }
}
```

## GET /api/current
ローカル保存の最新レコード（`data.json` 相当）。Supabase 直取得ではない。

Query: なし
Response: 保存が無い場合は `{}` を返す。

## GET /api/range
生ログを返す。

Query（公開契約）
- `store` or `store_id`: 店舗識別子
- `limit`: 返却件数（`MAX_RANGE_LIMIT` で clamp）

Behavior
- Supabase には `ts.desc` で問い合わせ、レスポンスは `ts.asc` に整列。
- サーバ側の時間フィルタは実装しない（夜窓はフロント側）。
- **`from` / `to` は公開契約に含めない**（バックエンドの legacy 実装に依存しない）。

Response
```json
{
  "ok": true,
  "rows": [
    {
      "ts": "...",
      "men": 0,
      "women": 0,
      "total": 0,
      "store_id": "...",
      "weather_code": "...",
      "weather_label": "...",
      "temp_c": 0,
      "precip_mm": 0,
      "src_brand": "..."
    }
  ]
}
```

Errors
- `422 { ok:false, error:"invalid-parameters", detail:"..." }`
- `502 { ok:false, error:"upstream-supabase", detail:"..." }`
- `502 { ok:false, error:"upstream-google-sheets", detail:"..." }`（legacy 経路）

## GET /api/forecast_today
Night window 向けの予測。

Query
- `store` or `store_id`

Behavior
- `ENABLE_FORECAST=1` のときのみ有効。無効時は 503。

Response
```json
{ "ok": true, "data": [ { "ts": "...", "men": 0, "women": 0, "total": 0 } ] }
```

Error
```json
{ "ok": false, "error": "forecast-disabled" }
```

## GET /api/forecast_next_hour
次の 1 時間程度の予測。

Query
- `store` or `store_id`

Behavior / Error / Response は `/api/forecast_today` と同様。

## GET /api/second_venues
二次会スポット（補助）。

Query
- `store` or `store_id`

Response
```json
{ "ok": true, "rows": [] }
```

Note
- 本番 UX は map-link 方式（frontend）。backend は最小応答の維持のみ。

## GET /api/range_multi
複数店舗の range データを一括取得。

Query
- `stores`: カンマ区切りの店舗スラグ（最大40）
- `limit`: 各店舗の返却件数

Behavior
- **ThreadPoolExecutor(12)** で Supabase に並列クエリ。
- 各店舗の結果は `ts.asc` で返却。

Response
```json
{
  "ok": true,
  "by_slug": {
    "shibuya": { "rows": [ { "ts": "...", "men": 0, "women": 0, "total": 0, ... } ] },
    "shinjuku": { "rows": [ ... ] }
  }
}
```

## GET /api/forecast_today_multi
複数店舗の forecast_today を1リクエストで返すバッチエンドポイント。

Query
- `stores`: カンマ区切りの店舗スラグ（最大40）

Behavior
- `ENABLE_FORECAST=1` のときのみ有効。無効時は 503。
- **ThreadPoolExecutor(max_workers=12)** で並列推論。
- Flask プロセス内キャッシュ（TTL 60s）を `forecast_today` と共有。キャッシュヒット時は推論スキップ。

Response
```json
{
  "ok": true,
  "by_slug": {
    "shibuya": { "ok": true, "data": [ { "ts": "...", "men": 0, "women": 0, "total": 0 } ] },
    "shinjuku": { "ok": true, "data": [ ... ] }
  }
}
```

Error
- `422 { ok: false, error: "no-valid-stores" }` — 有効な店舗スラグが 0 件
- `503 { ok: false, error: "forecast-disabled" }` — ENABLE_FORECAST=0

## GET /api/megribi_score
各店舗の最新データから megribi_score を計算して返す。

Query
- `store`: 単一店舗スラグ（省略時は全店舗）
- `stores`: カンマ区切りの複数店舗スラグ

Behavior
- Supabase backend 必須。**ThreadPoolExecutor(12)** で並列取得。
- 結果はスコア降順でソート。

Response
```json
{
  "ok": true,
  "data": [
    {
      "slug": "shibuya",
      "score": 0.785,
      "total": 42,
      "men": 20,
      "women": 22,
      "female_ratio": 0.524,
      "occupancy_rate": 0.525,
      "ts": "2026-03-28T20:15:00+09:00"
    }
  ]
}
```

Error
- `501 { ok: false, error: "supabase-required" }` — data_backend が supabase 以外

## GET /api/forecast_accuracy
店舗別の学習時精度メトリクス（MAE / RMSE）を返す。

Behavior
- `metadata.json`（学習時に生成）から `metrics` フィールドを読み取り返却。
- メトリクスは学習後にしか更新されないため、CDN キャッシュを長め（`s-maxage=3600`）に設定。

Response
```json
{
  "ok": true,
  "trained_at": "2026-03-28T05:30:00+09:00",
  "metrics": {
    "ol_nagasaki": {
      "overall": { "men_mae": 2.34, "women_mae": 1.89, "total_mae": 4.23, "men_rmse": 3.01, "women_rmse": 2.45 },
      "weekend_night": { "men_mae": 3.10, "total_mae": 5.55 }
    }
  }
}
```

Error
- `404 { ok: false, error: "metadata-not-found" }` — metadata.json が存在しない
- `404 { ok: false, error: "no-metrics-in-metadata" }` — メトリクスフィールドがない
- `500 { ok: false, error: "metadata-parse-error" }` — JSON パースエラー

## GET|POST /tasks/collect
単店舗の legacy 収集（GAS append）。

Input
- `store`, `men`, `women`, `ts`（ISO8601, timezone 必須）

Response
- 正常: `{ ok: true }`
- 検証エラー: `400 { ok:false, error:"..." }`

## GET|POST /tasks/multi_collect
本番収集の入口（`collect_all_once` を実行し Supabase `logs` へ書き込む）。

Behavior
- デフォルト: **202 Accepted** + バックグラウンドスレッド実行（非同期）。
- `?mode=sync`: 旧同期モード（完了まで待機）。
- `/tasks/multi_collect/status`: 実行中タスクのステータス確認。

Response（デフォルト 202）
```json
{ "ok": true, "task": "collect_all_once", "stores": 38, "mode": "async" }
```

Response（`?mode=sync` 200）
```json
{ "ok": true, "task": "collect_all_once", "stores": 38 }
```

## GET|POST /api/tasks/collect_all_once
`/tasks/multi_collect` の alias。

## GET /tasks/tick
レガシー。単店舗 + ローカル保存。`WINDOW_START`/`WINDOW_END` の範囲外ではスキップ。

Response (例)
```json
{ "ok": true, "skipped": true, "reason": "outside-window", "window": { "start": "...", "end": "..." } }
```

## GET /tasks/seed
ローカル保存の初期化（当日分が無い場合のみ書き込み）。

## GET|POST /tasks/update_second_venues
任意。`GOOGLE_PLACES_API_KEY` がある場合のみ Places API から取得し Supabase に保存する。
失敗しても `{ ok:true, updated:0 }` を返す。
