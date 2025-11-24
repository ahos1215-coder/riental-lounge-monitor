# ENV — めぐりび / MEGRIBI 環境変数ガイド

このドキュメントは、めぐりび / MEGRIBI プロジェクトで使う **環境変数の一覧と役割** をまとめたもの。  

- 「どの値を変えればどんな挙動が変わるか」
- 「Supabase 一本化後に最低限必要な値」
- 「まだ残っている Google スプレッドシート / GAS 系の値」

を一箇所で把握できるようにする。

---

## 0. 基本方針

- 本番も開発も、**環境変数で挙動を切り替える**。
- 現在の優先度は  
  1. Supabase での 38 店舗自動収集  
  2. その後、バックエンドも Supabase ログ前提に寄せていく  
- Google スプレッドシート / GAS は **当面はサブ（バックアップ）扱い**。  
  必要になったときにだけ `ENABLE_GAS` などを ON にして使う。

---

## 1. どこで環境変数を使っているか

大きく分けて 3 系統ある。

1. **Flask バックエンド本体**  
   - ファイル: `oriental/config.py`, `app.py`, `oriental/routes/forecast.py` など  
   - `/api/range`, `/api/forecast/next_hour` などの挙動に影響

2. **マルチ店舗データ収集スクリプト**  
   - ファイル: `multi_collect.py`  
   - オリエンタルラウンジ全 38 店舗を巡回して Supabase へ書き込む  
   - 必須: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` など

3. **（将来）フロントエンド側で使う予定の環境変数**  
   - 例: `NEXT_PUBLIC_API_BASE_URL`, Web Push 用のキー など  
   - 現時点のリポジトリでは **まだ未使用**。必要になったらここへ追記する。

---

## 2. 最低限セットしておきたい値（優先度高）

### 2-1. 実運用でほぼ固定する値

```env
TIMEZONE=Asia/Tokyo
役割: すべての「日付・時間」をどのタイムゾーンで扱うか

使用箇所: oriental/config.py

メモ:

cron-job.org など、スケジューラ側のタイムゾーンも 必ず Asia/Tokyo に合わせる。

将来的に海外店舗を扱う場合は、店舗ごとに変える可能性あり。

2-2. Supabase 連携（マルチ店舗収集の要）
multi_collect.py を Supabase 専用で動かすときに必須。

env
コードをコピーする
SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
# 旧キー（互換用）:
# SUPABASE_SERVICE_KEY=xxxxxxxxxxxxxxxx
SUPABASE_URL

Supabase プロジェクトの URL（ダッシュボードの「Project URL」）

SUPABASE_SERVICE_ROLE_KEY

サービスロールキー。サーバー側から書き込み専用で使うキー

SUPABASE_SERVICE_KEY は古い名称。
コード上は「SERVICE_ROLE_KEY が設定されていなければ SERVICE_KEY を見る」ようになっているので、今後は ROLE_KEY をメインに使う。

2-3. 店舗・時間帯の基本設定
env
コードをコピーする
STORE_NAME=長崎店
WINDOW_START=19
WINDOW_END=5
STORE_NAME

API レスポンスやログに表示する「店舗名」。

現状はバックエンドのメインターゲット店舗（例: 長崎店）。

WINDOW_START, WINDOW_END

「夜の時間帯」の開始・終了時刻（時のみ、0–23）。

たとえば 19〜5 なら「19:00〜翌 05:00」を夜として扱う。

/api/range のデフォルト期間や予測で利用。

3. Flask バックエンド（共通設定）
3-1. データ保存関連
env
コードをコピーする
DATA_DIR=data
DATA_FILE=data.jsonl
MAX_RANGE_LIMIT=50000
DATA_DIR

ローカルのデータ保存ディレクトリ。デフォルトは data/。

DATA_FILE

来店ログを追記していく JSON Lines ファイル名。

Supabase 完全移行後も、ローカルバックアップとして残しておく前提。

MAX_RANGE_LIMIT

/api/range?limit=... の最大値。

大きくしすぎるとレスポンスが重くなるので、上限管理用。

3-2. HTTP アクセス制御
env
コードをコピーする
HTTP_TIMEOUT_S=12
HTTP_RETRY=3
HTTP_USER_AGENT=Mozilla/5.0 ...
TARGET_URL=https://oriental-xxxxx.com/...
TARGET_URL

人数取得元の「公式サイト URL」。
HTML の構造が変わるとここから先のパーサーを修正する必要がある。

HTTP_TIMEOUT_S

店舗サイトにアクセスするときのタイムアウト秒数。

HTTP_RETRY

失敗したときに何回までリトライするか。

HTTP_USER_AGENT

アクセス元として名乗る User-Agent。
必要に応じて curl/… ではなくブラウザっぽい文字列に変更する。

3-3. ログ出力
env
コードをコピーする
LOG_LEVEL=INFO
Python ログのレベル（DEBUG, INFO, WARNING, ERROR など）。

開発時は DEBUG、本番では基本 INFO 以上を想定。

3-4. Flask 実行関連
env
コードをコピーする
FLASK_DEBUG=0
PORT=8000
FLASK_DEBUG

Flask のデバッグモード ON/OFF（1/0）。

Render 本番では 0（OFF） を前提。

PORT

ローカルで python app.py したときのポート番号。

Render ではプラットフォーム側の PORT が自動で注入される想定。

4. 予測 API 用の環境変数
ファイル: oriental/routes/forecast.py

env
コードをコピーする
ENABLE_FORECAST=1
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5
ENABLE_FORECAST

0/1 フラグ。0 のときは /api/forecast/... 系エンドポイントは 503 を返す。

モデルが未準備のときは 0 にしておく。

FORECAST_FREQ_MIN

何分ごとに予測を更新するか（キャッシュ有効期限）。
例: 15 → 15 分ごと。

NIGHT_START_H, NIGHT_END_H

予測対象の「夜の時間帯」（時のみ）。
WINDOW_START, WINDOW_END と合わせておくと分かりやすい。

※ モデルの保存ディレクトリ・ファイル名はコード側で固定されており、
将来必要になればここに追記する。

5. マルチ店舗収集 multi_collect.py 用
Supabase 一本化の中心となる部分。
38 店舗分の HTML を定期的に取りに行き、Supabase の logs テーブルにインサートする。

5-1. Supabase 連携（再掲）
env
コードをコピーする
SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxx...
# 互換用:
# SUPABASE_SERVICE_KEY=xxxxxxxx...
上記が正しく入っていないと 一件も Supabase に保存されない。

5-2. 店舗巡回パラメータ
env
コードをコピーする
BETWEEN_STORES_SEC=5
何秒ごとに次の店舗へ移るか。

サイトへの負荷を下げるためのスロットル。

38 店舗 × 5 秒 ≒ 190 秒（約 3 分強）で一周。

5-3. 天気取得関連
env
コードをコピーする
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873
ENABLE_WEATHER

0/1 フラグ。1 のときは Open-Meteo から天気を取得して Supabase に一緒に保存する。

WEATHER_LAT, WEATHER_LON

対象エリアの緯度・経度。
長崎店だけなら長崎周辺、マルチ店舗なら共通の代表地点でよい。

5-4. GAS / Google スプレッドシート連携（サブ扱い）
env
コードをコピーする
ENABLE_GAS=0
GAS_URL=https://script.google.com/macros/s/xxx/exec
GAS_WEBHOOK_URL=https://script.google.com/macros/s/yyy/exec
GAS_MAX_RETRY=3
現在の方針では Supabase をメインとし、
GAS は「どうしてもバックアップが欲しいときだけ ON」にする。

ENABLE_GAS=0 にしておけば、GAS 側への POST は行われない。

GAS_URL, GAS_WEBHOOK_URL

それぞれ「通常保存用」「Webhook 通知用」などで使い分ける想定。

GAS_MAX_RETRY

GAS への送信が失敗したときの再試行回数。

6. 旧 Google スプレッドシート API（バックエンド側）
バックエンド単体でシートを読む／書くための URL。
Supabase 一本化の現在は 原則 OFF だが、コードとしては残してある。

env
コードをコピーする
GS_READ_URL=
GS_WEBHOOK_URL=
ファイル: oriental/config.py

いずれも空文字列のままでも動作はするが、
「シートから過去データを読み直したい」といった用途では設定が必要になる。

7. 推奨 .env 例
7-1. ローカル開発（長崎店・予測 OFF・Supabase ON）
env
コードをコピーする
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

FLASK_DEBUG=1
PORT=8000

ENABLE_FORECAST=0
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5

SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxxxxxxxxxx

BETWEEN_STORES_SEC=5
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873

ENABLE_GAS=0
GAS_MAX_RETRY=3
7-2. Render 本番（予測 ON 予定）
env
コードをコピーする
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

# Render 側で PORT は自動設定されるので指定不要
FLASK_DEBUG=0

ENABLE_FORECAST=1
FORECAST_FREQ_MIN=15
NIGHT_START_H=19
NIGHT_END_H=5

SUPABASE_URL=https://xxxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxxxxxxxxxxxxx

BETWEEN_STORES_SEC=5
ENABLE_WEATHER=1
WEATHER_LAT=32.744
WEATHER_LON=129.873

ENABLE_GAS=0
GAS_MAX_RETRY=3
8. 今後追加しそうな環境変数（メモ）
現時点のコードではまだ使っていないが、設計上ほぼ確定しているものをメモしておく。
実際に実装したタイミングでこのセクションを正式化する。

近くの二次会候補（カラオケ・ダーツ・ホテル・ラーメン）表示用

PLACES_API_PROVIDER（例: google_places など）

PLACES_API_KEY

Web プッシュ通知 / PWA 用

WEBPUSH_PUBLIC_KEY

WEBPUSH_PRIVATE_KEY

または OneSignal / Firebase などを採用する場合はそのキー類

以上。
このファイルは「どの環境変数をいじれば、めぐりびがどう変わるか」を確認する辞書として使う。
値を追加・削除したら、必ずここも更新して「次の ChatGPT / 将来の自分」に引き継ぐこと。