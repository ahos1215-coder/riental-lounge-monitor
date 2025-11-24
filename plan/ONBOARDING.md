ONBOARDING.md — めぐりび / MEGRIBI 開発クイックスタート

最終更新: 2025-11-22
対象ブランチ: main
対象コミット: 85fdee9（ /mnt/data/riental-lounge-monitor-main.zip と同一）

このドキュメントは、新しくプロジェクトに参加した開発者 / 次の ChatGPT が、
現在のコードベースと運用方針を最短で把握するための「入口」用メモです。

サービス名: めぐりび / MEGRIBI（旧: Oriental Lounge Monitor）

リポジトリ名: riental-lounge-monitor-main（typo だがそのまま運用中）

ここを読めば、「何を作っていて」「どこを触れば」「どうやって動くか」がざっくり分かる、を目標にしています。
詳細な仕様やコマンドは、必要に応じて ARCHITECTURE.md, RUNBOOK.md, API_CONTRACT.md などを参照してください。

1. これは何か（プロジェクト概要）

めぐりび / MEGRIBI は、

相席ラウンジ系店舗（現在は オリエンタルラウンジ長崎店 1店舗 を主対象）

男女来店人数の「現在値」と「今後 1 時間〜当日中の予測」

夜時間帯（19:00〜翌 5:00）に絞った可視化

を提供する、非公式の“やさしい混雑情報ダッシュボード” です。

現状の構成はざっくり以下の通りです。

スクレイピング & ログ収集（Flask / Python）

公式サイトの店舗ページから、定期的に「男性◯名 / 女性◯名」の文言を取得。

取得結果を /data/log.jsonl などのローカルファイルに追記。

将来的には Postgres / Supabase に一本化予定（現時点は JSON ファイル + Google スプレッドシートが主）。

予測モデル（XGBoost）

過去の人数・時間帯・天気などから 「今から 1 時間」と「今日の残り時間帯」 の人数を予測。

モデルや前処理コードは oriental/ml/ 配下に配置。

API からは /api/forecast_next_hour, /api/forecast_today として利用可能。

ダッシュボード UI（Next.js + Chart.js）

frontend/ 以下に Next.js 16（App Router）で構築中。

バックエンド API から人数・予測データを取得し、

時系列グラフ

1 時間後の予測カード

今日の推移プレビュー
を表示する SPA 風ダッシュボード。

本番運用（Render + cron-job.org）

Python バックエンドは Render（Starter プラン想定）にデプロイ。

cron-job.org から /tasks/collect などのタスク用エンドポイントを 5〜15 分間隔で叩き、
夜間のみ自動収集が回るようにしている。

今後は、

複数店舗対応（全 38 店舗 + 相席屋 / JIS など）

Supabase / Postgres へのデータ保存・集計 API

LINE 通知やよりリッチな UI

といった拡張を前提に設計されていますが、このコミット時点では「長崎店 1 店舗 + JSON ログ + Google Sheets + XGBoost + Next.js ダッシュボード」 が現役です。

2. 前提となる構成（ディレクトリ & コンポーネント）

リポジトリの要点だけを抜き出すと、現状はこんな構成です。

riental-lounge-monitor-main/
├─ app.py                      # Flask アプリのエントリーポイント
├─ oriental/                   # バックエンド本体（Flask Blueprints, モデル, ユーティリティ）
│  ├─ __init__.py              # create_app() が定義されている
│  ├─ config.py                # 環境変数 → 設定オブジェクト
│  ├─ routes/                  # API / タスク / ヘルスチェックなど
│  │  ├─ data.py               # /api/range などデータ取得系
│  │  ├─ forecast.py           # /api/forecast_* 系
│  │  ├─ tasks.py              # /tasks/collect /tasks/forecast など収集タスク
│  │  └─ health.py             # /healthz
│  ├─ ml/                      # 予測モデル関連（XGBoost）
│  │  ├─ preprocess.py
│  │  ├─ model_xgb.py
│  │  └─ forecast_service.py
│  ├─ utils/                   # ログ保存・共通処理
│  │  └─ storage.py            # log.jsonl の読み書き・集計など
│  └─ templates/               # 旧来のシンプルな HTML ダッシュボード（Chart.js）
│     └─ index.html
├─ data/
│  ├─ data.json                # 直近データのサマリ（旧方式）
│  └─ log.jsonl                # 取得ログ（1 行 1 レコード）
├─ scripts/                    # ローカルの補助スクリプト
│  ├─ aggregate_10m.py         # 10 分集計用スクリプト
│  ├─ export_csv.py            # ログ → CSV 変換
│  └─ supabase_test_insert.py  # Supabase への試験書き込み
├─ artifacts/                  # 学習済みモデル等（XGBoost の pickle など）
├─ frontend/                   # Next.js ダッシュボード（本命 UI）
│  ├─ package.json             # Next 16 / Tailwind / Chart.js 等
│  ├─ next.config.mjs
│  └─ src/app/                 # App Router（`page.tsx` など）
├─ app/                        # ルート直下の React/Next プレビュー用 `page.tsx` など（実験中）
└─ plan/                       # 設計・運用ドキュメント
   ├─ ONBOARDING.md            # このファイル
   ├─ ARCHITECTURE.md          # アーキテクチャの詳細
   ├─ API_CONTRACT.md          # API 仕様
   ├─ CRON.md                  # cron-job.org / 定期実行の整理
   ├─ ENV.md                   # 必要な環境変数
   ├─ RUNBOOK.md               # 運用手順（Runbook）
   └─ ROADMAP.md               # 今後の開発ロードマップ


ポイント

現状の本番運用の主役は app.py + oriental/ 以下。

ダッシュボードは Next.js（frontend/） と、シンプルな Flask + テンプレート版 の 2 系統が存在するが、
新規開発は Next.js 側を優先する方針。

Supabase への接続スクリプトはありますが、まだ本番フローには組み込まれていません（scripts/supabase_test_insert.py で動作確認する段階）。

3. 開発者の前提知識

このリポジトリを触るうえで、ざっくり次の知識があるとスムーズです。

Python / Flask

Blueprint / create_app() パターンが分かる程度。

requirements に入っているライブラリ（requests, pydantic, xgboost, pandas など）を恐れず触れるレベル。

JavaScript / TypeScript + React / Next.js

frontend/src/app/page.tsx を読んで編集できるくらい。

fetch でバックエンド API を叩いてグラフに流し込む流れが理解できれば十分。

Git / GitHub / Render / cron-job.org の基本操作

コミット / push / デプロイの一連の流れ。

Render の Web Service（Python）に環境変数を入れてデプロイする。

cron-job.org で URL を定期的に叩く設定を行う。

（余裕があれば）機械学習の基礎

XGBoost による回帰モデル。

学習データの前処理（時間系特徴量、one-hot など）。

ただし、モデルを一から設計し直すフェーズではなく、
「既存の学習済みモデルをどう呼び出して、どう可視化するか」が主テーマ。

4. ローカル起動の最短パス
4-1. 事前準備

Python 3.10 〜 3.11 系を推奨（3.13 でも動く想定だが、ライブラリ互換性に注意）。

Node.js 20 系（Next.js 16 の要件を満たすもの）。

Windows / macOS / Linux いずれでも可。以下は概ね共通の流れです。

4-2. リポジトリの展開

すでに zip を展開済みの想定です。まだの場合は以下。

unzip riental-lounge-monitor-main.zip
cd riental-lounge-monitor-main


以降、カレントディレクトリは常に riental-lounge-monitor-main/ を前提とします。

4-3. Python 仮想環境と依存インストール
# 仮想環境の作成
python -m venv .venv

# 有効化（Windows PowerShell）
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

# 依存パッケージのインストール
pip install --upgrade pip
pip install -r requirements.txt

4-4. 最低限の環境変数設定

開発用には、以下を .env に書いておけば最低限動きます。
（詳細は plan/ENV.md を参照）

# 監視対象店舗（暫定: 長崎店）
TARGET_URL=https://oriental-lounge.com/nagasaki/   # 実際の URL に合わせて
STORE_NAME=長崎店

# 夜時間帯の定義（19:00〜翌5:00）
NIGHT_START_H=19
NIGHT_END_H=5

# 予測機能（最初は無効でもよい）
ENABLE_FORECAST=0      # まずは 0 にしておくとシンプル
FORECAST_FREQ_MIN=15   # 予測間隔（分）


.env を置いておくと、python-dotenv 経由で oriental/config.py が読み込んでくれます。

予測モデルを試したい場合は ENABLE_FORECAST=1 に変更しますが、
最初は 収集と可視化だけを確認する方がトラブルが少ないです。

4-5. Flask バックエンドの起動
# ルートディレクトリで
python app.py


デフォルトで http://127.0.0.1:5000 で起動します。

起動ログに Running on http://0.0.0.0:5000 などが出ていれば OK。

動作確認用の簡易チェック:

# ヘルスチェック
curl http://127.0.0.1:5000/healthz

# 最新 120 レコードの取得
curl "http://127.0.0.1:5000/api/range?limit=120" | python -m json.tool

# 予測 API（ENABLE_FORECAST=1 のとき）
curl "http://127.0.0.1:5000/api/forecast_next_hour" | python -m json.tool
curl "http://127.0.0.1:5000/api/forecast_today" | python -m json.tool


これで バックエンド側の基本 API は一通り確認できます。

4-6. Next.js ダッシュボードの起動
cd frontend

# 依存インストール（初回のみ）
npm install

# バックエンド URL を設定
# frontend/.env.local に以下のような形で記載
# NEXT_PUBLIC_BACKEND_URL=http://localhost:5000

# 開発サーバ起動
npm run dev


ブラウザで http://localhost:3000 にアクセスすると、

「長崎店」の現在人数

「今から 1 時間」の予測（ENABLE_FORECAST=1 のとき）

当日 19:00〜05:00 の推移グラフ（実績＋予測）

を確認できるダッシュボードが表示されます。

5. 想定ユースケース（何をするときにどこを見るか）

めぐりび / MEGRIBI のコードベースは、主に以下の 3 種類の用途を想定しています。

データ収集・ロジックの改善

スクレイピングの壊れ（HTML 構造変更）に対応する。

oriental/routes/tasks.py や oriental/utils/storage.py を修正し、
ログフォーマットや異常値処理を調整する。

予測モデル・特徴量の改善

oriental/ml/preprocess.py, model_xgb.py, forecast_service.py を中心に、
入力特徴量やパラメータを追加・変更する。

学習フローは別途（今後整備予定の）ノートブックやスクリプトで行い、
学習済みモデルは artifacts/ 以下に保存する。

UI / UX の改善

frontend/src/app/page.tsx などを編集し、
表示する指標（例: 「男女比」「ピーク時間帯」「今から◯分後」など）を見直す。

将来的な複数店舗対応（店舗切り替えタブ・距離順ソートなど）は、
ROADMAP の P0 / P1 項目に沿って実装していく。

6. Render / 本番運用の概要

※ここは 現状の想定・設計 をまとめています。実際の Render 設定は
ダッシュボードや管理画面を別途確認してください。

6-1. バックエンド（Render）

Render の Web Service として app.py を gunicorn app:app で起動。

環境変数は plan/ENV.md の内容をベースに、

TARGET_URL, STORE_NAME, NIGHT_START_H, NIGHT_END_H

予測関連: ENABLE_FORECAST, FORECAST_FREQ_MIN

（必要に応じて）Google Sheets / Supabase 接続情報
等を設定。

6-2. 定期実行（cron-job.org）

cron-job.org から Render 上の /tasks/collect を 5〜15 分間隔で実行。

時間帯は 19:00〜翌 5:00 のみに制限している（夜営業帯のみ記録するため）。

将来的には /tasks/forecast や、複数店舗をまとめて収集するタスクを追加する計画。

6-3. フロントエンド（Next.js）

現時点ではローカル開発が中心。

将来的には Vercel などに frontend/ をデプロイし、
NEXT_PUBLIC_BACKEND_URL を Render の URL に向ける運用を想定。

7. ディレクトリ構成の要点（どこを触るべきか）

よく触るであろう場所 と、触る前に慎重になった方がよい場所 を区別しておきます。

7-1. よく触る場所（変更歓迎）

oriental/routes/data.py

API のパラメータ仕様・レスポンス形式を調整する場所。

例: /api/range に store パラメータを追加して複数店舗対応する、など。

oriental/routes/forecast.py

予測 API のエンドポイント定義。

新しい予測指標（例: 「ピーク時間帯」「男女比予測」）を追加したい場合はここから。

frontend/src/app/page.tsx & frontend/src/app/components/*

ダッシュボードの UI 実装。

グラフの種類追加・カードデザイン変更・説明テキストの改善などはこの辺を中心に。

plan/ 配下のドキュメント

本 ONBOARDING を含め、プロジェクトの「頭の中」をコードとずらさないための場所。

仕様変更や新機能追加のたびに、ここも追従させる前提。

7-2. 慎重に触るべき場所

oriental/utils/storage.py

ログフォーマットや読み書きロジックの中枢。

ここを変えると 既存 log.jsonl との互換性 に影響するため、
変更時は必ずテストデータで確認した上で、API 側も合わせて修正する。

oriental/ml/*

予測モデル本体。

既存モデルを壊すと、ダッシュボード側でエラーになりやすいため、
新しいモデルは 別ファイル / 別 artifact 名 で追加し、
動作確認後に切り替える方が安全。

scripts/supabase_test_insert.py

現状「試験用」「お試し」スクリプト。

将来的に本番フローに組み込む場合は、
oriental/data/ 配下に正式な Provider として移す想定。

8. 次に読むべきドキュメント

この ONBOARDING はあくまで「地図の鳥瞰図」です。
詳細は、用途ごとに以下のドキュメントを参照してください。

設計を俯瞰したいとき
→ plan/ARCHITECTURE.md
（バックエンド・フロントエンド・データフローの図と説明）

API の仕様を正確に知りたいとき
→ plan/API_CONTRACT.md
（各エンドポイント・パラメータ・レスポンス例）

本番運用をどう回すか知りたいとき
→ plan/RUNBOOK.md
（Render / cron-job.org の設定や、障害時の対応フロー）

環境変数・機密値を整理したいとき
→ plan/ENV.md

今後どこから手を付けるべきか知りたいとき
→ plan/ROADMAP.md
（P0 / P1 / P2 の開発優先順位）

9. よくある質問（想定問答）

Q. プロジェクト名が「めぐりび / MEGRIBI」なのに、リポジトリ名が riental-lounge-monitor-main なのはなぜ？
A. 元々「Oriental Lounge Monitor」として始まった名残です。
名前を変えるには連携している各種設定（Render, cron-job.org, フロントエンドなど）の変更が必要になるため、
ひとまず コードとサービス名は分けて考える 方針にしています。

Q. Supabase はもう本番で使っている？
A. いいえ、このコミット時点では まだ「試験段階」 です。
scripts/supabase_test_insert.py でログを投げてみることはできますが、
公式フローは log.jsonl + Google Sheets ベースになっています。
Supabase への移行は plan/ROADMAP.md の P1 に位置付けられています。

Q. 複数店舗対応はどこから触ればいい？
A. 現時点では、店舗はほぼ STORE_NAME + TARGET_URL の 1 セット前提です。
複数店舗化の第一歩としては、

plan/ROADMAP.md の P0 記述を確認

plan/API_CONTRACT.md に store パラメータを追加する案を整理

oriental/routes/data.py / oriental/utils/storage.py を
「store_id（または店舗名）」をキーに扱えるように拡張

という流れが想定されています。
10. 今後の TODO / 拡張アイデア（ざっくり）

詳細は ROADMAP.md に譲りますが、ONBOARDING 視点での「次の一手」をまとめておきます。
P0（最優先）
① Supabase での 38 店舗・天気込み自動収集の本番化

現在「試験中」

これが安定すれば “どこでも動く” データ基盤が成立

ここが成功すれば以降の API・UI・ML が全部スムーズになる

P0.5（すぐ着手したい）
② Supabase 一本化（Sheets/GAS の撤去）

Sheets はほぼ使わない方針

当面のバックアップ用途に残すが、メインデータは Supabase に移行

DB Provider（SupabaseProvider）の実装
→ /api/range を Supabase 参照に切替
→ バックエンドの「真実のデータ源」を変更する

P1（P0完了後にすぐ始めたい）
③ 複数店舗対応

「store=nagasaki」「store=shibuya」などを API に追加

Next.js 側で店舗切り替え UI

Supabase logs のデータを可視化

距離/混雑/営業状態ソートなども可能になる

P1.5
④ 独自ドメイン（meguribi.com 想定）

Render → meguribi.com

Next.js（Vercel）で meguribi.com/dashboard のような構成も可能

ドメイン移行は Supabase/API/フロントが最低限揃ってからの方が安全

7. 今後追加したい大きめ機能（アイデアメモ）

Supabase 38 店舗自動収集 → Supabase 1 本化 → マルチ店舗ダッシュボード
までが一通り落ち着いたあとに、以下のような「ユーザー体験」を強くする機能も検討している。

### 7-1. 二次会スポット表示

- 各店舗ページの中に、
  - カラオケ / ダーツ / ホテル / ラーメン など
  - 「その店の近くで二次会に使えそうなお店」をカード表示する機能
- データの取り方
  - 現時点の想定では、Google Places API 等の「地図系外部サービス」を使って検索
  - めぐりび側は、緯度経度とカテゴリを渡して、良さそうな候補だけ表示する
- 役割
  - 「今日はここに行こうかな？」と思った時に、その後の動き方まで含めてサポートする
  - 公式ではないけど、公式の周辺ビジネスを広げる“非公式ガイド”的な立ち位置

### 7-2. LINE を使わない Web 通知（PWA）

- LINE Messaging API は費用がかかるため、
  - 「スマホのホーム画面に追加した Web アプリ」として通知を送る方向を検討中
- 技術的には
  - Next.js フロントを PWA 化（manifest + Service Worker）
  - Web Push API + Supabase テーブルで購読情報を管理
  - cron などから「今夜のおすすめ」通知を送るイメージ
- iPhone の前提
  - iOS の場合、ホーム画面に追加された PWA でないと Web Push を受け取れないため、
    UI で「ホーム画面に追加してください」という導線を作る想定
- 優先度
  - Supabase 移行とマルチ店舗対応が完了したあと、余裕が出てきたフェーズで検討する
