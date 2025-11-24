# めぐりび / MEGRIBI — RUNBOOK（運用手順書）

最終更新: 2025-11-22  
対象ブランチ: `main`  
対象コミット: `85fdee9` + 同 zip に含まれる未コミットファイル（`multi_collect.py`, `frontend/` など）  
対象フォルダ: `riental-lounge-monitor-main/`

この Runbook は、次の ChatGPT / 将来の自分が「今の構成と運用方法」を一発で思い出せるようにするためのドキュメントです。  
詳細な設計方針は `ARCHITECTURE.md`、今後やることの優先順位は `ROADMAP.md` を参照してください。

---

## 0. プロジェクトの現在地（運用目線の要約）

- プロジェクト名: **めぐりび / MEGRIBI**  
- 目的:
  - 相席ラウンジ系店舗（現在はオリエンタルラウンジ全 38 店舗を想定）の  
    「男女来店人数」と「近未来の混み具合」を見える化する
  - 天気データも合わせて集め、将来の機械学習に使う
- データパイプライン（2025-11-22 時点の運用前提）
  - 収集は **Supabase ログテーブルを主軸** とした多店舗収集スクリプト `multi_collect.py` を中心に設計
  - `/tasks/collect` エンドポイントから 38 店舗を一括スクレイピング → Supabase `logs` テーブルへ upsert
  - 旧 Google スプレッドシート / GAS パイプラインのコードは「互換性維持のために残してあるが、当面は使わない」方針
- 表示:
  - フロントエンドは Next.js 16（`frontend/`）で構築中
  - ローカル開発でダッシュボードを確認可能
  - 将来は「近くのお店（バー・カラオケ・ダーツ・ラーメンなど）」「Web プッシュ通知（PWA）」も組み込む予定
- 本番運用:
  - バックエンドは Render（Python / Flask）にデプロイ済み
  - 定期収集は cron-job.org から Render の `/tasks/collect`（もしくは `/tasks/tick` の旧ルート）を叩く構成を想定
  - 現時点では「Supabase 38 店舗収集の試験運用中」で、完全本番切り替えは ROADMAP に沿って行う

---

## 1. 環境と主要 URL 一覧

### 1.1 バックエンド（Flask）

- ローカル開発
  - ベース URL: `http://127.0.0.1:8000`
  - ヘルスチェック: `http://127.0.0.1:8000/healthz`
  - データ取得例:  
    - `GET /api/range?limit=120`  
    - `GET /api/range?from=2025-11-01&to=2025-11-02&limit=50000`
- Render（本番 / ステージング）
  - 例: `https://riental-lounge-monitor.onrender.com`  
    ※現時点でサービス名は旧名のまま。将来 `meguribi.com` の独自ドメインをかぶせる想定。
  - 代表エンドポイント
    - `GET /healthz`
    - `GET /api/range`
    - `POST /tasks/collect`（新: 多店舗 Supabase 収集）
    - `POST /tasks/collect_single`（旧: 長崎店のみ・GAS 経由、当面非推奨）

### 1.2 フロントエンド（Next.js 16）

- ローカル開発
  - デフォルト URL: `http://localhost:3000`
  - `app/page.tsx` … トップのダッシュボード
  - 近くのお店カード / 予測プレビュー / フィードバックボタンなどを実装中
- 本番デプロイ
  - まだ「本番向けの Vercel / Render Frontend」は未決定
  - 現状はローカル確認のみ  
  - 将来、独自ドメイン `meguribi.com` 配下に Next.js をデプロイする想定

### 1.3 データストア

- Supabase
  - プロジェクト名: `meguribi`（仮。実際の名称は Supabase コンソールで確認）
  - 主要テーブル（現行想定）
    - `logs`
      - `id` … PK（UUID / bigint）  
      - `store_id` … 店舗 ID（`stores.json` の ID と対応）  
      - `brand` … `'oriental_lounge'` など  
      - `ts` … 計測時刻（UTC or JST + offset）  
      - `men`, `women`, `total` … 来店人数  
      - `weather_code`, `temperature`, `precip_mm`, `wind_speed` … 天気関連  
      - `source` … `'scraper_v1'` などのバージョンタグ
    - `stores`
      - `id` … 店舗 ID  
      - `brand` … ブランド名（oriental / jis / aisekiya など将来用）  
      - `name`, `area`, `lat`, `lon`, `url` など
- ローカル JSON（開発・学習用）
  - `data/log.jsonl` … 旧ロギング（1 行 1 レコードの JSON Lines）
  - `data/data.json` … 集約済みデータ（単店舗）
  - `data/data_10m.json` … 学習用に 10 分刻みに整形した JSON

### 1.4 レガシー（当面は使わないが残っているもの）

- Google スプレッドシート / GAS
  - 旧構成では Render → GAS → スプレッドシート → Supabase という経路
  - 現在の方針: **Supabase 直接書き込みがメイン**  
    GAS / スプレッドは「将来バックアップ用途で復活させるかも」という位置づけ

---

## 2. ローカル開発の基本フロー

### 2.1 Python バックエンドの起動

1. ルートディレクトリへ移動

   ```powershell
   cd "C:\Users\<YOU>\Desktop\All Python project\ORIENTAL\riental-lounge-monitor-main"
仮想環境を作成・有効化（初回のみ）

powershell
コードをコピーする
python -m venv .venv
.\.venv\Scripts\activate
依存パッケージをインストール

powershell
コードをコピーする
pip install --upgrade pip
pip install -r requirements.txt
.env を作成

plan/ENV.md を見ながら、最低限以下を設定（ローカル開発用）

env
コードをコピーする
# 基本
FLASK_ENV=development
DEBUG=1
BASE_URL=http://127.0.0.1:8000
TARGET_URL=https://oriental-lounge.com/nagasaki
STORE_NAME=長崎店
TIMEZONE=Asia/Tokyo

# ログ保存先
DATA_DIR=./data

# Open-Meteo（ローカル開発で天気を触る場合）
WEATHER_BASE_URL=https://api.open-meteo.com/v1/forecast

# Supabase（多店舗収集を試すときに設定）
SUPABASE_URL=<あなたの Supabase URL>
SUPABASE_SERVICE_ROLE_KEY=<Service Role Key>
※値の詳細は ENV.md を参照。Supabase 関連は試験中のため、まだ空でも動くようになっている箇所もある。

バックエンド起動

powershell
コードをコピーする
.\.venv\Scripts\activate
python app.py
動作確認

powershell
コードをコピーする
curl.exe -s http://127.0.0.1:8000/healthz | python -m json.tool
curl.exe -s "http://127.0.0.1:8000/api/range?limit=120" | python -m json.tool
正常なら {"ok": true, ...} が返る。

2.2 Next.js フロントエンドの起動
フロントエンドディレクトリへ移動

powershell
コードをコピーする
cd frontend
依存インストール（初回のみ）

powershell
コードをコピーする
npm install
開発サーバー起動

powershell
コードをコピーする
npm run dev
ブラウザで http://localhost:3000 を開く

近くのお店カード

19:00〜05:00 の実績グラフ / 予測プレビュー

「お持ち帰りできた」「クソの役にも立たなかった」などのフィードバックボタン（将来実装）
を確認・改修していく。

3. 多店舗データ収集（Supabase 版）の運用
3.1 処理の流れ（概念）
/tasks/collect へリクエスト（cron-job.org から 5 分おきなど）

oriental.routes.tasks.tasks_collect_all が呼ばれる

内部で multi_collect.collect_all_once() を実行

multi_collect.py が stores_config（38 店舗の設定）を順番に処理

店舗ごとに公式サイトをスクレイピングし、男女人数を取得

Open-Meteo API から天気情報を取得

Supabase logs テーブルへ upsert（バルクでまとめて送信）

レスポンスとして、収集結果の概要（件数やエラー数など）を JSON で返す

3.2 必要な環境変数（Supabase 収集用）
詳細は ENV.md に譲るが、最低限以下が必要:

env
コードをコピーする
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=xxxxx   # Service Role Key を使う（書き込み権限あり）

# 収集間隔・チューニング用（すべて multi_collect.py 側で参照）
BETWEEN_STORES_SEC=3              # 店舗ごとのインターバル（秒）
BULK_UPSERT_CHUNK_SIZE=50         # Supabase へ送る一括件数
OPEN_METEO_BASE_URL=https://api.open-meteo.com/v1/forecast
※値を変えたら、必ず小規模テスト（2〜3 店舗だけ）でエラーやレートリミットを確認する。

3.3 手動で 1 回だけ実行する場合（ローカル）
powershell
コードをコピーする
# バックエンドが起動している前提
curl.exe -s -X POST "http://127.0.0.1:8000/tasks/collect" | python -m json.tool
レスポンス例:

json
コードをコピーする
{
  "ok": true,
  "stores_processed": 38,
  "inserted": 38,
  "errors": []
}
エラーがあれば errors 配列に店舗名とメッセージが入る。
その場合は、対象店舗の公式サイトの HTML 構造が変わっていないか確認する。

3.4 旧パイプライン（単店舗 + GAS）の扱い
/tasks/collect_single /tasks/multi_collect_legacy /tasks/tick など
→ 旧構成との互換性のために残してあるが、基本は 使わない。

将来的に Google スプレッドシートをバックアップ用途で使う場合だけ

GAS Webhook URL を復活

GS_WEBHOOK_URL, GS_READ_URL などの環境変数を設定

tasks.py 内の「legacy」ルートを順番に見直す

4. cron-job.org / Render を使った本番収集
4.1 推奨構成（Supabase 多店舗版）
Render 側で Flask アプリをデプロイ

app.py がエントリポイント

環境変数は ENV.md の「本番相当」セットを参照して設定

SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY は必須

cron-job.org でジョブを作成

URL: https://riental-lounge-monitor.onrender.com/tasks/collect

メソッド: POST

実行間隔: 5 分おき（将来、実データを見ながら調整）

タイムゾーン: Asia/Tokyo

動作確認

ジョブを 1 回「手動実行」してステータス 200 を確認

Supabase の logs テーブルを確認し、直近の ts が現在時刻付近になっていることを確認

4.2 停止・一時停止の方法
一時的に止めたい場合

一番安全なのは「cron-job.org のジョブを一時停止」

完全に止める／Render 側から止めたい場合

Render ダッシュボード → 該当サービス → Suspend

もしくは COLLECT_ENABLED=0 のようなフラグを環境変数で導入（今後の改善余地）

5. 予測モデル（XGBoost）の運用
※このあたりはまだ「ローカルでの試験運用」段階。
精度を本気で上げるのは 3 か月後以降でよく、「手間を増やさずに土台だけ用意しておく」方針。

5.1 ローカルでの学習フロー
ログ整形（必要に応じて）

基本は data/data_10m.json をそのまま使う

新しく Supabase からエクスポートしたい場合は、別途スクリプトで
logs テーブル → 10 分刻み JSON に変換する

学習スクリプトの実行

powershell
コードをコピーする
.\.venv\Scripts\activate
python scripts/train_local.py ^
  --input data/data_10m.json ^
  --tz Asia/Tokyo ^
  --out artifacts/nagasaki ^
  --freq_min 10
--freq_min は 10 or 15

10 分: 精度は上げやすいが、データ量が増える

15 分: データ量が減って軽くなるが、時間解像度は落ちる

今の方針: 「手間を増やさない」ので、まずは 10 分で統一し、後で必要なら 15 分版も作る。

学習結果

artifacts/nagasaki/ 配下にモデルファイルとメタ情報が出力される

将来的に LightGBM へ移行する場合も、このディレクトリ構造はなるべく維持する

5.2 予測 API の有効化（ローカル）
.env に以下を追加

env
コードをコピーする
ENABLE_FORECAST=1
FORECAST_MODEL_DIR=./artifacts/nagasaki
FORECAST_FREQ_MIN=10
NIGHT_START_H=19
NIGHT_END_H=5
バックエンドを再起動

動作確認

powershell
コードをコピーする
curl.exe -s "http://127.0.0.1:8000/api/forecast/preview" | python -m json.tool
※エンドポイント名は API_CONTRACT.md で最終決定されたものに合わせること。
ここでは仮に /api/forecast/preview と表記している。

6. トラブルシューティング（よくある詰まりポイント）
6.1 「データが増えていない / グラフが真っ白」
Supabase の logs テーブルを確認

今日の日付のレコードがあるか

store_id や ts が正しく入っているか

/tasks/collect のレスポンスを直接確認

powershell
コードをコピーする
curl.exe -s -X POST "https://riental-lounge-monitor.onrender.com/tasks/collect" | python -m json.tool
ok: false や errors に何か入っていれば、そのメッセージに従って調査

Render のログを確認

HTTP タイムアウト / Supabase への接続エラーが出ていないか

Next.js の API 呼び出し確認

frontend/ 内の fetch 先 URL が、最新のバックエンド URL と一致しているか

CORS エラーが出ていないか（ブラウザの DevTools → Network タブ）

6.2 「Open-Meteo で 403 / 429 が出る」
BETWEEN_STORES_SEC を小さくしすぎていると、レートリミットにかかる可能性あり

対処:

まず 3 秒以上に設定し直す

それでもだめなら、一時的に天気取得を OFF にするオプションを multi_collect.py に追加する（将来の改善）

6.3 「Supabase 側でエラー」
よくある原因

Service Role Key ではなく anon key を使っている

テーブル名やカラム名のスペルミス

ts のタイムゾーンが不整合で unique 制約に引っかかる

対処

Supabase コンソール → logs テーブル → 「Insert」クエリの履歴 / エラーを確認

必要なら multi_collect.py の payload 生成部分を一度 print して中身を確認

7. 今後の UI / 通知機能の運用メモ（まだ実装前）
ここは「運用時に気を付けたいこと」を先にメモだけしておくセクション。
実装が進んだら、具体的な手順に差し替える。

7.1 二次会候補のお店表示
目的:

めぐりびで「今どの店が良さそうか」を見たあと
→ その近くで行けるカラオケ・ダーツ・ラーメン・ホテルなどを一覧で出す

想定データソース:

Google Places API / Hotpepper / ぐるなび など

運用時のポイント:

外部 API の無料枠を超えないようにキャッシュ層（Supabase nearby_places テーブルなど）を用意する

API キーは .env / Render の環境変数で管理し、Git には絶対に入れない

7.2 Web プッシュ通知（PWA）での「擬似 LINE 通知」
目的:

LINE Messaging API は月額コストがかかるため、
iPhone / Android の「ホーム画面に追加」＋ Web プッシュ通知で代替したい

方針メモ:

Next.js 側で PWA 化（manifest.json, service worker）

Web Push 用の VAPID キーを生成し、サーバー側（Flask or Next.js API）から送信

「毎朝の混雑予報」「今から 1 時間の混み具合」などを通知内容として検討

運用上の注意:

通知の送りすぎは即アンインストールにつながるので、
「1 日 1 通まで」「ユーザー側で頻度を選べる」などの制御が必要

実際の送信バッチ（cron）や失敗時のリトライは、この Runbook に追記する

8. 既存エンドポイント仕様（現行版サマリ）
詳細は API_CONTRACT.md に任せるが、運用上よく使うものだけ抜粋しておく。

GET /healthz

サーバーの簡易ヘルスチェック

GET /api/range

クエリ: from, to, limit（いずれも任意）

返却: 時系列の来店人数データ（men / women / total）

GET /api/current

各店舗の「いま」の人数スナップショット

GET /api/forecast/preview（名称は後で確定）

今日の夜〜明け方までの簡易予測（ダッシュボード上部のプレビュー用）

POST /tasks/collect

多店舗データ収集（Supabase へ upsert）

POST /tasks/collect_single（legacy）

長崎店のみを対象にした旧収集処理

9. バックアップ / リストア方針（暫定）
Supabase

管理画面の「Backups」機能を ON（プランに応じて設定）

週 1 回程度、logs テーブルを CSV / Parquet でエクスポートしてローカルに保存

ローカル JSON

data/log.jsonl / data/data_10m.json を Git 管理はしない（サイズ肥大化を防ぐ）

必要なら backups/ ディレクトリを作り、日付付きでコピーしておく

Google スプレッドシート（将来再利用する場合）

GAS 側で「バックアップ用シート」に定期コピーするようなスクリプトを別途用意

10. Git / 開発の進め方（簡易）
変更前に必ず git status で現状を確認

小さい単位で commit を刻む

plan/*.md（ドキュメント）を更新したら、必ずコミットメッセージに [docs] などを入れて分かりやすくする

bash
コードをコピーする
git status

git add plan/RUNBOOK.md
git commit -m "[docs] update runbook for Supabase multi-store"
git push
11. ChatGPT / AI を使うときのコツ
まず ONBOARDING.md → ARCHITECTURE.md → この RUNBOOK.md の順で要点を読ませる

「いまどのフェーズか」を毎回最初に伝える

例: 「今は Supabase 多店舗収集のテスト中で、Next.js の UI にはまだ反映していない」

大きなリファクタや設計変更は、必ず ROADMAP.md にメモしてからやってもらう
→ 後続の ChatGPT / 自分が迷子にならないようにする