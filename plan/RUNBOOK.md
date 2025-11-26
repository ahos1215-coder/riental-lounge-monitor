# めぐりび / MEGRIBI RUNBOOK（運用手順）
Last updated: 2025-11-26, commit: TODO  
対象ブランチ: main  
対象フォルダ: `riental-lounge-monitor-main/`

この Runbook は運用担当が「今日の構成を把握し、基本の確認と障害対応」を素早く行うためのメモです。詳細な設計は ARCHITECTURE.md、環境変数は ENV.md を参照してください。

---

## 0. 現在の構成（Supabase メイン）
- 収集: `multi_collect.py` を `/tasks/tick` 等から呼び出し、38 店舗分を Supabase `logs` テーブルに insert。
- DATA_BACKEND=supabase のとき
  - `/api/range` は SupabaseLogsProvider で `/rest/v1/logs` を読み出し（store_id, ts 範囲, limit）。
  - `/api/forecast_*` は ForecastService が SupabaseLogsProvider で履歴を取り、XGBoost で予測。
  - `/api/meta` は AppConfig.summary() を返し、Supabase 設定や window, timeout などを可視化。
- legacy（GAS + GoogleSheet + ローカル JSON）はバックアップ/デバッグ用途。Supabase に問題がある場合に DATA_BACKEND=legacy で戻す。
- フロント（Next.js /frontend）は API 仕様を従来どおり `/api/range`, `/api/forecast_*` を利用。

---

## 1. 基本 URL / サービス
- Render 本番: `https://riental-lounge-monitor.onrender.com`（例）
  - `/healthz`
  - `/api/meta` … data_backend / supabase.url / supabase.service_role / store_id を確認
  - `/api/range`
  - `/api/forecast_next_hour`, `/api/forecast_today`
- ローカル: `http://127.0.0.1:8000`（python app.py）

---

## 2. 起動・再起動・設定反映
- Render 環境変数を変更したら「Deploy latest commit」または「Restart service」で反映。
- Supabase のキー（SUPABASE_SERVICE_ROLE_KEY 等）は Git にコミットしない。Render Environment にのみ設定。
- ローカル開発:
  - `.env` を用意して `python app.py`
  - DATA_BACKEND=supabase で Supabase を叩く／DATA_BACKEND=legacy でローカル/GAS を試す

---

## 3. ヘルスチェック / 動作確認
1) 設定の確認 `/api/meta`  
```sh
curl -s https://<BASE>/api/meta | python -m json.tool
```
- `data.data_backend` が `supabase`
- `data.supabase.url`, `service_role` が true
- `data.supabase.store_id` が意図どおり
- `window.start/end`, `http_timeout`, `http_retry`, `max_range_limit`

2) レンジ取得 `/api/range`  
```sh
curl -s "https://<BASE>/api/range?from=2024-11-01&to=2024-11-02&limit=200&store_id=ol_nagasaki" | python -m json.tool
```
- `ok: true` で rows が返る
- DATA_BACKEND=supabase なら logs 由来のフィールド（store_id, weather_code, …）が入る

3) 予測 `/api/forecast_next_hour` / `/api/forecast_today`  
```sh
curl -s "https://<BASE>/api/forecast_next_hour?store_id=ol_nagasaki" | python -m json.tool
curl -s "https://<BASE>/api/forecast_today?store_id=ol_nagasaki" | python -m json.tool
```
- `ok: true` と freq_min, data[] が返る
- 必要に応じて ENABLE_FORECAST=1 を確認（api/meta で見える）

4) ヘルスチェック  
```sh
curl -s https://<BASE>/healthz | python -m json.tool
```
- `/healthz` が正式なヘルスエンドポイント。`/tasks/*` をヘルスチェックに使わない。

---

## 4. Render 側での操作メモ
- Environment 変更 → 「Deploy latest commit」または「Restart service」で反映。
- Supabase 関連の env はダッシュボードでのみ管理（Git に置かない）。
- DATA_BACKEND を変更したら /api/meta で反映を確認。

---

## 5. 障害対応フロー（例）
1) 症状確認  
   - `/api/range` が 502 `upstream-supabase` を返す → Supabase 側障害の可能性
2) 一時対応  
   - Render の Environment で `DATA_BACKEND=legacy` に変更 → 再起動  
   - legacy データ（GAS + ローカル JSON）で最低限の可視化を継続
3) 復旧確認  
   - `DATA_BACKEND=supabase` に戻し、/api/meta と /api/range / /api/forecast_* を再確認

---

## 6. ローカル開発の確認手順
- Supabase を叩く場合（.env に Supabase 設定を入れる）:
  ```sh
  python app.py
  curl -s http://127.0.0.1:8000/api/meta | python -m json.tool
  curl -s "http://127.0.0.1:8000/api/range?limit=10&store_id=ol_nagasaki" | python -m json.tool
  ```
- legacy だけ試す場合:
  - `.env` で `DATA_BACKEND=legacy` に設定し `python app.py`
  - 同様に /api/meta, /api/range を確認

---

## 7. 収集タスク運用ルール（重要）
- 役割分担
  - `/tasks/collect`: 単一レコード + GAS append 専用（テスト・手動用）。GET/POST で store/men/women/ts を受け付け、バリデーション NG は 400。
  - `/tasks/multi_collect`: 38 店舗一括収集。`collect_all_once()` を実行し Supabase logs に保存。正常時 `{"ok": true, "stores": 38, "task": "collect_all_once", "duration_sec": ...}`。異常時も JSON を返す（HTTP は実装準拠）。
  - `/api/tasks/collect_all_once`: `/tasks/multi_collect` のエイリアス。
- Health Check 禁止事項
  - Render の Health Check Path に `/tasks/collect` `/tasks/multi_collect` `/api/tasks/collect_all_once` を設定しない。
  - ヘルスチェックは `/healthz` または `/api/meta` を使用する。
- 定期収集（cron）
  - 5 分ごとの定期収集は `/tasks/multi_collect` か `/api/tasks/collect_all_once` のどちらか一方に統一。
  - `/tasks/collect` は cron からは叩かない（テスト・手動確認専用）。
- 簡易確認コマンド
  - ローカル:  
    ```sh
    python app.py
    curl "http://127.0.0.1:5000/healthz"
    curl "http://127.0.0.1:5000/tasks/multi_collect"
    ```
  - Render Web Shell（例）:  
    ```sh
    curl -s http://127.0.0.1:10000/healthz
    # 必要に応じて
    curl -s http://127.0.0.1:10000/tasks/multi_collect
    ```
  - 実行時間の目安: 県別天気キャッシュありで **約 60〜70 秒**（duration_sec ログに表示）。

---

## 8. 収集タスクの概要・参照
- `/tasks/tick` → `multi_collect.collect_all_once()`
  - 38 店舗のスクレイピング → Supabase logs に upsert
  - 天気(Open-Meteo)は **都道府県単位で 1 回取得** し、pref キャッシュを 38 店舗で使い回す（座標は `STORES.pref` → `PREF_COORDS` → `WEATHER_LAT/LON` の順で決定）
- 必要な ENV: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / DATA_BACKEND / STORE_ID / (ENABLE_GAS が必要な場合は GAS_URL 等)

---
