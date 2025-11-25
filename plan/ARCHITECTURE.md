# めぐりび / MEGRIBI — アーキテクチャ概要

最終更新: 2025-11-22（ChatGPT Web）
対象ブランチ: main  
想定コミット: 85fdee9 付近  
対象フォルダ: `riental-lounge-monitor-main/`

> 目的:  
> 将来の自分 / 次の ChatGPT が、このリポジトリの中身と現在の方針  
> （Supabase 一本化・マルチ店舗対応・独自ドメイン `meguribi.com` 構想）を  
> できるだけ矛盾なく理解できるようにするためのアーキテクチャメモ。

---

## 0. システム全体像（What / Why）

### サービス概要

- サービス名: **めぐりび / MEGRIBI**
- ゴール:
  - 相席系ラウンジの「いま」の混み具合と「このあと」の予測を、やさしく見える化する。
  - 特にオリエンタルラウンジ全 38 店舗を起点に、将来的には相席屋 / JIS などへ拡張。
- ユーザー:
  - どの店に行けばよいか迷っている人（主に男性客）  
  - 将来的には「失敗しにくい夜遊びの地図」「やわらかい案内灯」として使ってもらう。

### アーキテクチャの大枠

現在のめぐりびは、ざっくり次の 4 レイヤで構成される。

1. **データ収集レイヤ**
   - 各店舗の公式サイト / API から男女人数を取得
   - 天気 API から天候・気温を取得
   - 5 分ごとに 38 店舗分を自動収集する Collector が中心（Render 上で稼働）

2. **永続化レイヤ（Supabase）**
   - 取得したデータを **Supabase（PostgreSQL）** の `logs` テーブルに保存
   - 店舗情報などは `stores` テーブルで管理
   - これまで使ってきた Google スプレッドシート + GAS は **原則廃止方向**  
     （必要になればバックアップ用途でのみ再利用）

3. **API / 予測レイヤ（Flask + ML）**
   - Python / Flask ベースのバックエンド
   - Supabase からログを読み出し、  
     - 生データの提供（/api/range など）
     - 機械学習モデル（XGBoost 等）による予測値の計算・返却
   - `/tasks/*` 系エンドポイントで、定期収集やモデル更新のトリガーも担当

4. **表示レイヤ（Next.js フロントエンド）**
   - `frontend/` 以下の **Next.js 16 (App Router)** で実装
   - 店舗ごとのカード表示、当日グラフ、1 時間先の予測プレビューなどを表示
   - 将来的には `meguribi.com` をフロントの独自ドメインとして運用予定

これらをつなぐ補助として、

- **cron-job.org**: 5 分おきに Render の `/tasks/tick` を叩いて収集を回す
- **Open-Meteo などの天気 API**: 天候・気温を取得
- （将来）**LINE Messaging API**: 混み具合通知や「今日どこ行く？」のレコメンド用

といった外部サービスが存在する。

---

## 1. テキスト版アーキテクチャ図

イメージを文字で残しておく。

```text
[ユーザーのブラウザ]
        |
        v
[Next.js Frontend (frontend/)]
        |
        | HTTPS (REST API)
        v
[Flask API (app.py / oriental/)]
        |
        | Supabase Python Client
        v
[Supabase (PostgreSQL: logs / stores)]
        ^
        |
        | 5分ごと (cron-job.org → /tasks/tick)
        |
[Collector: app/multi_collect.py (Render)]
        |
        +--> [Oriental Lounge 公式サイト/API]
        |
        +--> [Open-Meteo など天気 API]
※ 旧アーキテクチャでは、「Collector → GAS → Google Sheets → Render」が挟まっていたが、
　現在は Supabase に直接書き込む方針 で整理中。

2. ディレクトリ構成（アーキテクチャ視点）
※ 実際のファイル一覧は ONBOARDING.md やリポジトリを参照。ここでは役割だけ。

text
コードをコピーする
riental-lounge-monitor-main/
├─ app.py                 # Flask アプリのエントリポイント
├─ app/                   # マルチ店舗用 Collector など（新規領域）
│   └─ multi_collect.py   # 38店舗分の自動収集ロジック
├─ oriental/              # 旧「oriental lounge monitor」本体パッケージ
│   ├─ __init__.py
│   ├─ config.py          # 環境変数・設定読み込み
│   ├─ routes/
│   │   ├─ data.py        # /api/range などデータ系 API
│   │   └─ forecast.py    # /api/forecast/* など予測系 API（名前は仮）
│   ├─ tasks/             # /tasks/* の中身（collect / tick / forecast 等）
│   ├─ utils/             # 共通ユーティリティ
│   ├─ data/              # 旧ローカルデータ（JSON ログ等）※ Supabase 移行中
│   └─ ml/                # 学習・推論ロジック（XGBoost モデル等）
├─ data/
│   ├─ log.jsonl          # 旧ローカルログ（デバッグ用途）
│   ├─ data.json          # 旧ダッシュボード用キャッシュ
│   └─ stores.json        # 店舗マスタ（38 店舗分）※ Supabase `stores` と二重管理中
├─ frontend/              # Next.js 16 フロントエンド
│   ├─ app/
│   │   ├─ page.tsx       # トップダッシュボード
│   │   ├─ (stores)/[id]/page.tsx # 店舗別詳細ページ（拡張用）
│   │   ├─ components/    # グラフ・カード等の UI コンポーネント
│   │   └─ api/health/... # フロント側の簡易 API（ヘルスチェック等）
│   └─ ...                # Next.js 設定ファイル 等
├─ plan/                  # このファイルを含む設計ドキュメント群
│   ├─ ARCHITECTURE.md
│   ├─ API_CONTRACT.md
│   ├─ ENV.md
│   ├─ ROADMAP.md
│   └─ RUNBOOK.md など
└─ requirements.txt       # Python ライブラリ
3. バックエンド（Flask API）構成
3-1. エントリポイント: app.py
Flask アプリケーション本体を作成し、oriental パッケージの設定・ルートを読み込む。

Render では gunicorn app:app のような形で起動される想定。

主な責務:

ルーティングの登録

CORS 設定

ENABLE_FORECAST など環境変数の読み込み（oriental.config 経由）

3-2. 代表的なエンドポイント
※ 正式なパラメータは API_CONTRACT.md を参照。ここではざっくり。

GET /healthz

死活監視用。Render / cron-job.org からも利用。

GET /api/range

指定した店舗・期間のログ（男女人数 + 天気）を返す。

クエリ例: ?store=nagasaki&from=2025-11-13&to=2025-11-14&limit=50000

実装は oriental/routes/data.py 付近。

データソースは基本 Supabase logs テーブル（ローカル JSON はデバッグ用）。


GET /api/forecast/next_hour

Data source: forecast APIs use Supabase logs when DATA_BACKEND=supabase; legacy uses GoogleSheet/local backup.

ENABLE_FORECAST=1 のときのみ利用。

GET /api/forecast/today

当日夜（19:00〜翌 5:00）の履歴＋予測をまとめて返すロングレンジ API。

POST /tasks/tick

cron-job.org から 5 分おきに叩かれる。

内部で マルチ店舗 Collector を起動し、全店舗の最新値を Supabase に書き込む。

POST /tasks/forecast（名前は仮）

定期的なモデル再学習・予測キャッシュ更新用。

2025-11 時点では「構想」の段階で、実運用はまだ。

3-3. 設定・環境変数（概要だけ）
詳細は ENV.md に譲り、ここではアーキレベルの要点のみ。

SUPABASE_URL, SUPABASE_SERVICE_KEY

Supabase 用。バックエンドから直接 DB にアクセスする。

ENABLE_FORECAST

予測機能 ON/OFF。0 の場合、予測 API は固定値 or 404 にする方針。

FORECAST_FREQ_MIN

予測結果の時間粒度（例: 15）。

NIGHT_START_H, NIGHT_END_H

「夜の範囲」を定義。データ抽出・グラフ表示の基準。

4. データ収集レイヤ（Collector + バッチ）
4-1. 38 店舗マルチ Collector（現状の最重要ポイント）
実体: app/multi_collect.py

役割:

data/stores.json もしくは Supabase stores テーブルから
「収集対象店舗一覧（store_id / URL / タイムゾーン 等）」を読む。

各店舗の公式サイト / API から現在の男女人数を取得。

天気 API（Open-Meteo など）から該当エリアの天気・気温を取得。

上記をまとめて Supabase logs テーブルに一括 INSERT。

呼び出しフロー:

cron-job.org → POST /tasks/tick → multi_collect.collect_all()（名称は仮）

現在（2025-11 時点）の状況:

Supabase 38 店舗自動データ収集を試験中（天気込み）

試験が安定したら、

旧 Google スプレッドシート + GAS 経路は停止

すべて Supabase からグラフ・予測を行う

4-2. 天気データ取得
使用 API: Open-Meteo（無料 / 認証不要）をベースに設計。

取得内容（例）:

weather_code（天気記号）

temperature_2m（気温）

降水量・風速なども必要なら拡張可能。

取得した値は logs.weather_code / logs.temperature_c などのカラムに保存する想定。

4-3. 旧アーキテクチャ（廃止予定）
旧フロー:

Render (/tasks/collect) → GAS Webhook → Google Sheets → バックエンド API

方針:

普段使いでは Supabase を唯一のデータソースとする。

Sheets は「過去のデータが貴重」「緊急バックアップが欲しい」などの場合にのみ使用。

コード上も、旧 GAS 連携部は徐々に削除 or legacy として隔離する。

5. Supabase（DB）構成
※ 正確なカラム定義は Supabase ダッシュボードを参照。ここでは「どんな役割か」が分かるレベルで記載。

5-1. logs テーブル（来店ログ）
役割: すべての学習・グラフ・予測の根本データ。

想定カラム例:

id (uuid, PK)

store_id (text) … 例: nagasaki, shinjuku, shibuya など

ts (timestamptz) … 計測時刻（JST or 各店舗のローカルタイムゾーン）

men (int)

women (int)

total (int) … men + women（INSERT 時にサーバ側で自動計算してもよい）

weather_code (int) … Open-Meteo のコード

temperature_c (float)

created_at (timestamptz, default now())

利用箇所:

/api/range のグラフ描画

ML モデルの学習データ

「今日の傾向」「曜日別の平均」などの集計

5-2. stores テーブル（店舗マスタ）
役割: マルチ店舗対応の土台。ブランドや地域、表示順序などを管理。

想定カラム例:

id (text, PK) … nagasaki, umeda, shibuya 等、コードとして統一

brand (text) … oriental_lounge, aisekiya, jis など

name (text) … 表示名（例: オリエンタルラウンジ長崎）

area (text) … 地域（nagasaki, tokyo, osaka 等）

lat, lng (float) … 将来、距離ソートに利用

tz (text) … タイムゾーン（基本 Asia/Tokyo）

open_hour, close_hour (int) … 通常営業の時間帯

is_active (bool) … 収集対象かどうか

sort_order (int) … 一覧表示時の並び順

created_at, updated_at

利用箇所:

Collector の「どの店舗を回すか」の決定

フロントの店舗一覧（カード）の表示

将来の多ブランド対応（相席屋 / JIS）で特に重要

5-3. その他検討中のテーブル
forecasts_* 系

予測結果を Supabase にキャッシュしておくかどうかは検討中。

現状は「API が呼ばれるたびにサーバ側で計算する」構成で問題なし。

feedback

「お持ち帰りできた / できなかった」「役に立った / クソの役にも立たなかった」
などのユーザーフィードバックを保存する構想あり。

実装のタイミングで再度設計する。

6. 機械学習レイヤ（XGBoost → 将来 LightGBM も視野）
6-1. 現状の方針
モデル種類:

当面は XGBoost を採用（コード・ノウハウが既にある）。

将来、必要であれば LightGBM へ移行可能にしておく。

粒度:

15 分単位のデータで学習・予測する想定。
(FORECAST_FREQ_MIN=15 を前提にした設計が多い)

店舗ごとの扱い:

「各店舗ごとにローカルモデルを持つ」方針を重視。

都心と地方で傾向が大きく異なるため、グローバルモデルは優先度低め。

6-2. 学習・推論の流れ（ざっくり）
学習データ取得

Supabase logs から対象店舗の一定期間（例: 直近 90 日）を取得。

夜の時間帯（19:00〜翌 5:00）のレコードを中心に使用。

特徴量生成

過去数ポイントの男女人数（ラグ特徴）

曜日・祝日フラグ

天気コード・気温

学習

oriental/ml/ 以下のスクリプトで XGBoost を学習。

モデルファイルを artifacts/<store_id>/ に保存。

推論

/api/forecast/next_hour / /api/forecast/today で、

最新の logs を読み出し

必要な特徴量を組み立て

モデルをロードして予測値を生成

結果を JSON としてフロントへ返す。

6-3. 今後の改善アイデア（メモ）
予測値だけでなく p10 / p50 / p90 のような予測レンジを出してバンド表示する。

学習を 週 1 回 程度のジョブにまとめ、
Render ではなくローカル PC や一時ワーカーで実行する運用。

Supabase に「学習済みモデルのメタ情報（学習期間、スコア等）」を保存し、
どのモデルがいつのデータで学習されたかを追えるようにする。

7. フロントエンド（Next.js 16）構成
7-1. 技術スタック
Next.js 16（App Router）

TypeScript

Tailwind CSS

Chart.js + chartjs-adapter-date-fns（時間軸のグラフ）

将来的に:

フィードバックボタン

距離順 / 営業時間順ソート

「今夜どこが良さそうか」をカードで出すレコメンド

7-2. 主な画面
/（トップダッシュボード）

近くの店舗 / 人気店舗の一覧カード

「今から 1 時間の予測」「今日の推移」のグラフ

/stores/[id]（店舗別ページ）

特定店舗にフォーカスした詳細グラフ

将来的には「曜日別の傾向」「過去 30 日のピークタイム」なども追加予定。

7-3. API との連携
GET /api/range

当日 or 指定日の履歴を取得して Chart.js に流す。

GET /api/forecast/next_hour

「今から 1 時間の予測プレビュー」用。

GET /api/forecast/today

実測値＋予測を 1 本のグラフとして表示したい場合に利用。

7-4. ドメイン構想
現状:

Render のデフォルト URL（バックエンド） + ローカル開発での Next.js。

将来:

meguribi.com を取得し、フロントエンドに紐づける。

バックエンドは api.meguribi.com のようなサブドメインに切り分ける案もあり。

CORS / HTTPS 設定は、フロントとバックエンドをどこに置くか決まってから調整。

8. 外部サービスと連携
Supabase

メインのデータストア。

認証などは将来のユーザー機能追加時に利用予定（現状は DB のみ）。

cron-job.org

無料の外部 Cron サービス。

5 分おきに /tasks/tick を叩き、Collector を動かす。

将来的に高トラフィックになったら、自前のスケジューラや有料サービスへ移行も検討。

Open-Meteo（天気 API）

認証不要で使いやすい。

将来、精度や安定性の観点で別サービスへ切り替える可能性あり。

Google スプレッドシート + GAS

旧アーキテクチャ。原則、今後は使わない方針。

「古いデータを引き上げる」「緊急避難的なバックアップ」としてのみ温存する可能性。

9. 「今」と「これから」の整理
9-1. 現在（2025-11-22 時点）
Supabase 38 店舗自動収集（天気込み）を 試験運用中。

バックエンドの主要 API は動作しており、Next.js フロントからのグラフ表示も可能。

Google スプレッドシートは ほぼ使っていない（残っているのは過去資産）。

9-2. 直近の優先度（アーキテクチャ視点）
Supabase 収集の安定運用

38 店舗すべてで、欠損や 500 エラーが出ないようにする。

stores / logs のスキーマを確定させる（後から変えにくいので慎重に）。

Supabase 一本化

バックエンド & フロントが、原則 Supabase だけを見れば動く状態にする。

旧 Google Sheets ルートをコメントアウト or legacy ディレクトリへ退避。

マルチ店舗 UI の整備

Next.js 側で「エリア別」「ブランド別」「距離順」などが扱いやすい形にする。

独自ドメイン meguribi.com の導入

Supabase 周りが落ち着いたら着手。

どのホスティング（Vercel / Render / 他）にフロントを置くか決める。

10. 追加で確認したいこと（メモ）
この ARCHITECTURE.md を今後さらに精度を上げるために、
もし余裕があれば次の点を教えてもらえると嬉しいです。

Supabase logs / stores の実際のカラム名・型
（このファイルには役割だけを書いたので、ENV.md や別紙に正確な定義を置きたい）

Collector が現在参照しているマスタは

data/stores.json が正？

それとも stores テーブルが正？

予測 API のエンドポイント名・レスポンス JSON が
API_CONTRACT.md と完全に一致しているかどうか

11. 将来拡張メモ: 二次会スポット表示 & Web 通知（PWA）

ここからは、今すぐ実装しないが「めぐりび」にぜひ入れたい機能の設計メモ。

- A. 二次会スポット表示（カラオケ／ダーツ／ホテル／ラーメン）
- B. LINE を使わない Web プッシュ通知（PWA + Web Push）

どちらも「Supabase 38 店舗自動収集 → Supabase への本格移行 → マルチ店舗ダッシュボード」
が落ち着いてから着手する P3 項目という位置づけ。

---

### 11-A. 二次会スポット表示（カラオケ・ダーツ・ホテル・ラーメン）

#### 11-A-1. やりたいこと（UI イメージ）

- 店舗詳細ページ（長崎店など）の中に、
  - 「近くのお店（現在営業中のみ・サンプル）」のようなブロックを追加
  - カテゴリ例: カラオケ / ダーツ / ホテル / ラーメン
- カード UI はすでに作っているサンプル（距離・営業時間・口コミ・地図リンク）をほぼ流用
- 利用イメージ:
  - 「今からオリエンタルラウンジ行く → そのあとカラオケ or 朝まで空いてるバー」
  - 「ラストオーダー後に〆のラーメン」

#### 11-A-2. データの取り方

- めぐりび自身が「二次会店舗のマスタ」を持つのではなく、基本は外部 API で検索
  - 候補: Google Places API などの地図系サービス
  - 将来、必要なら Supabase に「おすすめ店の固定リスト」を持たせる余地も残す
- 店舗の緯度経度は `stores` テーブルに持っておき、
  - 「半径 300〜500m 以内」
  - カテゴリ（カラオケ／ダーツバー／ホテル／ラーメン）でフィルタ
  - 距離や評価順でソート
- 認証情報（API key）はバックエンド側で管理し、フロントには流さない方針

#### 11-A-3. API のざっくり設計案

- 新しいバックエンド API の例（Flask 側 or Next.js の API Route どちらでも可）

  - `GET /api/nearby_spots?store_id=nagasaki&category=karaoke`
  - レスポンスのイメージ:

    ```json
    {
      "ok": true,
      "data": [
        {
          "name": "カラオケ館 思案橋店",
          "category": "karaoke",
          "distance_m": 280,
          "rating": 3.9,
          "review_count": 215,
          "open_text": "～05:00 営業中",
          "is_open_now": true,
          "map_url": "https://maps.google.com/?q=...",
          "source": "google_places"
        },
        ...
      ]
    }
    ```

- 実装時のポイント:
  - フロントからは `/api/nearby_spots` だけを叩く
  - バックエンドが外部 API（Google Places など）に問い合わせて整形する
  - 将来、他社サービス（食べログ / ホットペッパーなど）に切り替えたくなっても、
    バックエンドの実装だけ差し替えればよい

#### 11-A-4. フロントエンド側の扱い

- Next.js の店舗詳細ページにセクションを追加
  - 例: 「近くのお店（現在営業中のみ・サンプル）」のすぐ下に「二次会候補」ブロックを並べる
- UI 的にやりたいこと
  - カテゴリごとにタブ or チップ（カラオケ / ダーツ / ホテル / ラーメン）
  - 「もっと見る」→ Google マップの検索結果へ飛ばす
- 優先度
  - Supabase まわりやマルチ店舗対応が安定したあとに着手する P3 項目

---

### 11-B. LINE を使わない Web 通知（PWA + Web Push）

#### 11-B-1. やりたいこと

- LINE Messaging API は有料になりやすいので、「できるだけ無料で通知をしたい」
- iPhone / Android のブラウザで
  - めぐりびのページをホーム画面に追加してもらう
  - その状態で Web プッシュ通知を受け取れるようにする
- 例:
  - 「今日は長崎店、22時以降に女性多めの予測です」
  - 「雨なので全体的に空き気味になりそう」などの一言通知

#### 11-B-2. 技術的な前提（特に iPhone）

- iOS Safari では、
  - Web Push を使うには「ホーム画面に追加された PWA」として動いている必要がある
  - ＝ユーザーに「ホーム画面に追加してください」と案内する UI が必要
- その代わり、LINE のような月額費用は不要で、
  - サーバ側（Flask or Next.js）とブラウザの間で Web Push をやり取りするだけで良い

#### 11-B-3. アーキテクチャのざっくり案

1. Next.js 側を PWA 化
   - `manifest.webmanifest` を追加
     - アプリ名（めぐりび / MEGRIBI）
     - アイコン類
     - 起動 URL など
   - Service Worker を追加
     - オフラインキャッシュ
     - 後で Web Push を受け取る処理をここに書く

2. Web Push の導入
   - VAPID 方式の Web Push を想定
   - フロント側:
     - 通知許可をユーザーに確認
     - `PushManager.subscribe()` でサブスクリプション情報を取得
     - それをバックエンドへ POST
   - バックエンド側:
     - Supabase に `push_subscriptions` テーブルを作成（例）
       - `id`
       - `endpoint`
       - `p256dh`
       - `auth`
       - `created_at`
       - `last_active_at`
     - Python or Node の Web Push ライブラリで通知を送信
     - 通知トリガーは
       - cron-job.org からのキック
       - or Supabase のスケジュール機能 / Render の cron など

3. どういうタイミングで通知するか（例）
   - 1 日 1 回、夕方に「今夜のおすすめ店舗」まとめ
   - 店舗ごとの「今日は比較的空きそう」情報
   - 将来的にはユーザーごとの「お気に入り店舗」設定があれば、それに紐づけた通知も可能

#### 11-B-4. セキュリティ / プライバシーの考慮

- ログイン機能がない場合、端末 ID はランダムなトークンをローカルに保存し、それと紐付けて Supabase に保存する想定
- 収集する情報は「通知のための最小限」にとどめる
- 通知文言も「混雑状況の案内」レベルにし、過度に個人情報に結びつく内容は扱わない

#### 11-B-5. 優先度

- Supabase 38 店舗の安定運用 → Supabase 1 本化 → マルチ店舗 UI
- そのあと、「ユーザーにとっての便利さアップ」のフェーズで検討する位置づけ（P3）
