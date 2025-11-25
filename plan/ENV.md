# ENV ― めぐりび / MEGRIBI 環境変数ガイド
Last updated: 2025-11-25（実装ソース: oriental/config.py :: AppConfig.from_env）

このドキュメントは、めぐりび / MEGRIBI プロジェクトで使う **環境変数の一覧と役割** をまとめたものです。  

- 「どの値を変えると挙動がどう変わるか」を即座に把握するためのメモ  
- Supabase 一本化後に最低限必要な値と、legacy バックアップの切り替えポイント  
- ローカルと Render 本番での置き場所の違い

---

## 0. 基本方針
- 本番も開発も、**環境変数で挙動を切り替える**。  
- 現在の優先度  
  1. Supabase での 38 店舗自動収集  
  2. バックエンドも Supabase ログ前提に揃える（DATA_BACKEND=supabase がデフォルト）  
- Google スプレッドシート / GAS は **legacy バックエンド** としてフォールバック用に温存（DATA_BACKEND=legacy のときのみ利用）

---

## 0.1 Supabase / backend 切り替え（最新）
- `DATA_BACKEND`（デフォルト: `supabase`）
  - `supabase`: `/api/range`, `/api/forecast_*` は Supabase logs `/rest/v1/logs` を読む
  - `legacy`: 旧 GoogleSheet + ローカル JSON を読む
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`（互換: `SUPABASE_SERVICE_KEY`）  
  Supabase REST 読み取り用。`DATA_BACKEND=supabase` で必須。
- `STORE_ID`  
  Supabase 利用時の既定 store_id。クエリ `store` / `store_id` で上書き可。互換キー `SUPABASE_STORE_ID` も読まれる。
- 予測 API のスイッチ
  - `ENABLE_FORECAST`=1 で /api/forecast_* を有効化（0 のとき 503）
  - `FORECAST_FREQ_MIN`（デフォルト 15）: 予測ポイントの刻み
  - `NIGHT_START_H` / `NIGHT_END_H`: 予測対象の夜間ウィンドウ（時のみ）

---

## 1. どこで環境変数を使っているか
1. **Flask バックエンド**  
   - ファイル: `oriental/config.py`, `oriental/routes/data.py`, `oriental/routes/forecast.py`  
   - `/api/range`, `/api/forecast_*` の挙動に影響
2. **マルチ店データ収集スクリプト**  
   - ファイル: `multi_collect.py`  
   - 38 店舗を巡回して Supabase に書き込む  
   - 主に `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` など
3. **（将来）フロントエンドで使う公開変数**  
   - 例: `NEXT_PUBLIC_API_BASE_URL` など  
   - 現時点では未使用。必要になったら追加。

---

## 2. 最低限セットしておきたい値（優先度高）

### 2-1. 時間帯・タイムゾーン
```env
TIMEZONE=Asia/Tokyo
WINDOW_START=19
WINDOW_END=5
```
- TIMEZONE: すべての日時計算の基準タイムゾーン
- WINDOW_START / WINDOW_END: 夜間ウィンドウ（時のみ）。予測・レンジ取得のデフォルト期間に利用。

### 2-2. Supabase 連携（メイン経路）
```env
SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxx...
# 互換:
# SUPABASE_SERVICE_KEY=xxxxxxxx...
DATA_BACKEND=supabase
STORE_ID=ol_nagasaki
```
- DATA_BACKEND: `supabase`（デフォルト）/ `legacy` の切り替え
- STORE_ID: Supabase 利用時の既定 store_id（クエリで上書き可）

---

## 3. Flask バックエンド共通設定

### 3-1. データ保存関連
```env
DATA_DIR=data
DATA_FILE=data.jsonl
MAX_RANGE_LIMIT=50000
DATA_BACKEND=supabase
STORE_ID=ol_nagasaki
```
- DATA_DIR, DATA_FILE: ローカル保存のベース/ファイル名（legacy/バックアップ用途）
- MAX_RANGE_LIMIT: `/api/range?limit=...` の上限（クランプ用）

### 3-2. HTTP アクセス制御
```env
HTTP_TIMEOUT_S=12
HTTP_RETRY=3
HTTP_USER_AGENT=OrientalLoungeMonitor/1.0 (+https://oriental-lounge.com)
TARGET_URL=https://oriental-lounge.com/stores/38
LOG_LEVEL=INFO
```

---

## 4. 予測 API 用
```env
ENABLE_FORECAST=1
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5
```
- ENABLE_FORECAST: 0/1 で /api/forecast_* の有効/無効
- FORECAST_FREQ_MIN: 予測ポイントの粒度（分）
- NIGHT_START_H / NIGHT_END_H: 予測対象の夜間ウィンドウ

---

## 5. マルチ店収集 multi_collect.py 用
```env
SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxx...
BETWEEN_STORES_SEC=5
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873
ENABLE_GAS=0
GAS_MAX_RETRY=3
```
- Supabase が有効なら GAS は OFF 推奨。ENABLE_GAS=1 で旧経路も利用可。

---

## 6. ローカル vs Render の置き場所
- **ローカル開発**: リポジトリ直下の `.env`（例: `riental-lounge-monitor-main/.env`）  
- **Render 本番**: Render ダッシュボードの Environment 設定に同じキーを登録（`.env` は不要）

---

## 7. 推奨 .env テンプレート
### 7-1. ローカル開発（Supabase ON, 予測 OFF の例）
```env
TIMEZONE=Asia/Tokyo
STORE_NAME=長崎店
TARGET_URL=https://example-oriental-nagasaki.com/
WINDOW_START=19
WINDOW_END=5

DATA_DIR=data
DATA_FILE=data.jsonl
MAX_RANGE_LIMIT=50000
HTTP_TIMEOUT_S=12
HTTP_RETRY=3
LOG_LEVEL=DEBUG

ENABLE_FORECAST=0
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5

SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxxxxxxxxxx
DATA_BACKEND=supabase
STORE_ID=ol_nagasaki

BETWEEN_STORES_SEC=5
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873

ENABLE_GAS=0
GAS_MAX_RETRY=3
```

### 7-2. Render 本番（予測 ON の例）
```env
TIMEZONE=Asia/Tokyo
STORE_NAME=長崎店
TARGET_URL=https://example-oriental-nagasaki.com/
WINDOW_START=19
WINDOW_END=5

DATA_DIR=data
DATA_FILE=data.jsonl
MAX_RANGE_LIMIT=50000
HTTP_TIMEOUT_S=12
HTTP_RETRY=3
LOG_LEVEL=INFO

ENABLE_FORECAST=1
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5

SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxxxxxxxxxx
DATA_BACKEND=supabase
STORE_ID=ol_nagasaki

BETWEEN_STORES_SEC=5
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873

ENABLE_GAS=0
GAS_MAX_RETRY=3
```

---

以上、環境変数を変えたらこのファイルも更新して「次の ChatGPT / 将来の自分」に引き継いでください。***
