# API_CONTRACT.md — 現行 API 仕様（バックエンド）

## 共通
- ベース: `/`（例: `https://riental-lounge-monitor.onrender.com`）
- すべて **JSON** を返します。
- 例外的な検証エラーを除き、基本は **200** を返します（失敗しない設計）。

---
## 1. GET `/api/range`
来店人数の行配列を返します。

### Query
- `from` : `YYYY-MM-DD`（省略時は今日）
- `to`   : `YYYY-MM-DD`（省略時は `from` または今日）
- `limit`: 取得上限。**1..MAX_RANGE_LIMIT** にクランプ（範囲外でも 200）。

### Response
```json
{
  "ok": true,
  "rows": [
    {
      "date": "2025-11-09",
      "time": "19:00",
      "store": "長崎店",
      "source": "https://oriental-lounge.com/stores/38",
      "men": 12,
      "women": 8,
      "total": 20,
      "ts": "2025-11-09T19:00:15+09:00"
    }
  ]
}
```

### 仕様
- `from > to` は 422 を返します（期間の逆転のみエラー）。
- `limit` は内部で `max(1, min(limit, MAX_RANGE_LIMIT))` に正規化。

---
## 2. GET `/api/current`
- 直近のサマリを返却。`{"ok": true, "data": {...}}`

## 3. GET `/api/range_prevweek`
- 前週同期間の概算データ（スタブ）。`{"ok": true, "data": {...}}`

## 4. GET `/api/summary`
- 画面上部の集計パネル等に利用（スタブ）。`{"ok": true, "data": {...}}`

## 5. GET `/api/meta`
- メタ情報（ウィンドウ・タイムゾーン・MAX_RANGE_LIMIT 等）。`{"ok": true, ...}`

## 6. GET `/api/heatmap`
- ヒートマップ用ダミーデータ（将来差し替え）。`{"ok": true, "data": [...]}`

## 7. GET `/api/stores/list`
- 将来の複数店舗化に向けた雛形。`{"ok": true, "data": []}`

---
## ログ
- `api_range.start` / `api_range.success` を INFO で出力。パラメータと正規化後の値（window/limit）を確認可能。
- Render では標準出力、ローカルでは `data/log.jsonl` に追記。

## バージョニング
- 大きな互換性変更が入る場合は `/v2/` を新設する方針。
