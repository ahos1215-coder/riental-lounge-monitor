# めぐりび / MEGRIBI RUNBOOK（運用手順）
Last updated: 2025-11-26, commit: TODO  
対象ブランチ: main  
対象フォルダ: `riental-lounge-monitor-main/`

この Runbook は運用担当が「今日の構成を把握し、基本の確認と障害対応」を素早く行うためのメモです。詳細な設計は ARCHITECTURE.md、環境変数は ENV.md を参照してください。

---

## 0. 現在の構成（Supabase メイン）
- 収集: `multi_collect.py` を `/tasks/tick` 等から呼び出し、38 店舗分を Supabase `logs` テーブルに insert。
- DATA_BACKEND=supabase のとき
  - `/api/range` は SupabaseLogsProvider で `/rest/v1/logs` を読み出し（store_id, ts 範囲, limit）。weather_code / weather_label / temp_c / precip_mm も返る。
  - `/api/forecast_*` は ForecastService が SupabaseLogsProvider で履歴を取り、XGBoost で予測。
  - `/api/meta` は AppConfig.summary() を返し、Supabase 設定や window, timeout などを可視化。
- legacy（GAS + GoogleSheet + ローカル JSON）はバックアップ/デバッグ用途。Supabase に問題がある場合に DATA_BACKEND=legacy で戻す。
- フロント（Next.js /frontend）は API 仕様を従来どおり `/api/range`, `/api/forecast_*` を利用。BACKEND_URL 経由の proxy で Flask に接続。

---

## 1. 基本 URL / サービス
- Render 本番: `https://riental-lounge-monitor.onrender.com`（例）
  - `/healthz`
  - `/api/meta` … data_backend / supabase.url / supabase.service_role / store_id を確認
  - `/api/range`
  - `/api/forecast_next_hour`, `/api/forecast_today`
- ローカル: `http://127.0.0.1:5000`（python app.py）

---

## 2. 起動・再起動・設定反映
- Render 環境変数を変更したら「Deploy latest commit」または「Restart service」で反映。
- Supabase のキー（SUPABASE_SERVICE_ROLE_KEY 等）は Git にコミットしない。Render Environment にのみ設定。
- ローカル開発:
  - `.env` を用意して `python app.py`
  - DATA_BACKEND=supabase で Supabase を叩く／DATA_BACKEND=legacy でローカル/GAS を試す

### コマンド例（PowerShell）
```ps1
# バックエンド起動
python app.py
# multi_collect を手動実行（38店舗一括）
python - <<'PY'
from multi_collect import collect_all_once
collect_all_once()
PY
# フロント起動
cd frontend
npm run dev
```

---

## 3. ヘルスチェック / 動作確認
1) 設定の確認 `/api/meta`  
```ps1
curl -s http://127.0.0.1:5000/api/meta | python -m json.tool
```
- data_backend が supabase、supabase.url/service_role が true、store_id が意図どおり
- window.start/end, http_timeout, http_retry, max_range_limit

2) レンジ取得 `/api/range`  
```ps1
curl -s "http://127.0.0.1:5000/api/range?from=2024-11-01&to=2024-11-02&limit=200&store=nagasaki" | python -m json.tool
```
- ok: true で rows が返る（weather_* も含まれる）

3) 予測 `/api/forecast_next_hour` / `/api/forecast_today`  
```ps1
curl -s "http://127.0.0.1:5000/api/forecast_next_hour?store=nagasaki" | python -m json.tool
curl -s "http://127.0.0.1:5000/api/forecast_today?store=nagasaki" | python -m json.tool
```
- ok: true と freq_min, data[] が返る（ENABLE_FORECAST=1 必要）

4) ヘルスチェック  
```ps1
curl -s http://127.0.0.1:5000/healthz | python -m json.tool
```
- `/healthz` が正式なヘルスエンドポイント。`/tasks/*` をヘルスチェックに使わない。

---

## 4. 収集タスク（multi_collect.py）のポイント
- 県別天気キャッシュ:
  - `PREF_COORDS`（県代表座標）+ `STORES.pref` を使い、pref ごとに 1 回だけ Open-Meteo を叩く。
  - 天気を取得できない場合は環境変数 `WEATHER_LAT/LON` へフォールバック。
- Supabase への保存:
  - `weather_code / weather_label / temp_c / precip_mm` を `logs` テーブルに保存。
- 実行時間の目安:
  - 県別キャッシュ後で **約 60〜70 秒** 程度。天気 API 呼び出し回数は「都道府県数＋α」まで圧縮。
- 手動実行:
  ```ps1
  python - <<'PY'
  from multi_collect import collect_all_once
  collect_all_once()
  PY
  ```

---

## 5. store 解決の仕様
- `oriental/utils/stores.py` の `resolve_store_identifier(raw, default_id)` を通じて、クエリ `store` / `store_id` を Supabase 用 store_id に変換。
  - 例: `store=nagasaki` → `store_id=ol_nagasaki`
  - 未指定なら AppConfig.store_id（ENV の STORE_ID）を使用。
- `/api/range`, `/api/forecast_*` はこのリゾルバ経由で Supabase に問い合わせる。

---

## 6. Next.js フロント（店舗切替と proxy）
- BACKEND_URL で Flask を指定し、フロントの `/api/forecast_next_hour`, `/api/forecast_today`, `/api/range` から proxy。
- 店舗切替:
  - `config/stores.ts` に店舗リスト（value=slug, label=表示名）。
  - URL の `/?store={slug}` で選択。`page.tsx` が useSearchParams で storeSlug を読み取り、各 API に `?store=...` を付与して再フェッチ。
- WeatherSummary:
  - `/api/range` の weather_* をカード表示し、選択店舗に応じて更新。

---

## 7. 障害対応フロー（例）
1) 症状確認  
   - `/api/range` が 502 `upstream-supabase` → Supabase 側障害の可能性  
2) 一時対応  
   - Render の Environment で `DATA_BACKEND=legacy` に変更 → 再起動  
   - legacy データ（GAS + ローカル JSON）で最低限の可視化を継続  
3) 復旧確認  
   - `DATA_BACKEND=supabase` に戻し、/api/meta と /api/range / /api/forecast_* を再確認

---

## 8. 定期収集・運用ルール
- 役割分担
  - `/tasks/collect`: 単一レコード + GAS append 専用（テスト・手動用）。GET/POST で store/men/women/ts を受け付け、バリデーション NG は 400。
  - `/tasks/multi_collect`: 38 店舗一括収集。`collect_all_once()` を実行し Supabase logs に保存。正常時 `{"ok": true, "stores": 38, "task": "collect_all_once", "duration_sec": ...}`。異常時も JSON を返す。
  - `/api/tasks/collect_all_once`: `/tasks/multi_collect` のエイリアス。
- Health Check 禁止事項
  - Render の Health Check Path に `/tasks/collect` `/tasks/multi_collect` `/api/tasks/collect_all_once` を設定しない。
  - ヘルスチェックは `/healthz` または `/api/meta` を使用。
- 定期収集（cron）
  - 5 分ごとの定期収集は `/tasks/multi_collect` か `/api/tasks/collect_all_once` のどちらか一方に統一。
  - `/tasks/collect` は cron からは叩かない（テスト・手動確認専用）。
- 簡易確認コマンド
  - ローカル:  
    ```ps1
    python app.py
    curl "http://127.0.0.1:5000/healthz"
    curl "http://127.0.0.1:5000/tasks/multi_collect"
    ```
  - Render Web Shell（例）:  
    ```ps1
    curl -s http://127.0.0.1:10000/healthz
    # 必要に応じて
    curl -s http://127.0.0.1:10000/tasks/multi_collect
    ```
  - 実行時間の目安: 県別天気キャッシュありで **約 60〜70 秒**（duration_sec ログに表示）。

---

以上を踏まえ、日常運用・障害対応・ローカル開発を進めてください。最新の仕様変更が入った場合は、本 Runbook と ENV.md / ARCHITECTURE.md の同期を忘れずに。 
