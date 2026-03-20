# API_CONTRACT
Last updated: 2025-12-23
Target commit: 10e50d6

MEGRIBI backend の公開契約。互換性を壊さないこと。

## Global rules
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）。
- レイヤ構造: Supabase → Flask → Next.js（frontend は Next API routes 経由で backend を呼ぶ）。
- `/api/range` の公開契約は **`store` / `limit` のみ**。サーバ側の時間フィルタは追加しない。
- Night window（19:00–05:00）はフロント責務。
- `MAX_RANGE_LIMIT` で `limit` を clamp（未指定時は `min(500, MAX_RANGE_LIMIT)`）。

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

## GET /api/heatmap
Placeholder。`{ ok: true, data: [] }`

## GET /api/range_prevweek
Placeholder。`{ ok: true, data: [] }`

## GET /api/summary
Placeholder。`{ ok: true, data: {} }`

## GET /api/stores/list
Placeholder。`{ ok: true, data: [] }`

## GET|POST /tasks/collect
単店舗の legacy 収集（GAS append）。

Input
- `store`, `men`, `women`, `ts`（ISO8601, timezone 必須）

Response
- 正常: `{ ok: true }`
- 検証エラー: `400 { ok:false, error:"..." }`

## GET|POST /tasks/multi_collect
本番収集の入口（`collect_all_once` を実行し Supabase `logs` へ書き込む）。

Response
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
