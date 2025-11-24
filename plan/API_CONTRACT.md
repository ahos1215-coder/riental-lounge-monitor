# めぐりび / MEGRIBI — API_CONTRACT.md

最終更新: 2025-11-22  
対象ブランチ: main  
対象コミット: 85fdee9（zip 内 .git/refs/heads/main より）  
システム名: めぐりび / MEGRIBI（旧 ORIENTAL LOUNGE Monitor）

このドキュメントは、めぐりびの「バックエンド API（Flask）」と
「フロントエンド（Next.js）」の間の取り決め（コントラクト）をまとめたものです。

- ChatGPT / gpt-codex / 将来の自分 が **コードを開く前にざっと読む想定**
- API を追加・変更するときは、ここ → 実装 → `requests.http` の順で更新する

> 今の方針:  
> - データ保管は **Supabase をメイン** にし、Google スプレッドシートは将来的に「バックアップ／検証用」に縮小  
> - まずはオリエンタルラウンジ全 38 店舗の自動収集＋天気  
> - その後、マルチ店舗 UI・通知（PWA）・二次会候補表示を拡張していく

---

## 0. 共通ルール

### 0-1. ベース URL

ENV.md で定義している値を参照する。

- ローカル開発  
  - `BACKEND_BASE_URL=http://127.0.0.1:5000`
- 本番（Render）  
  - `BACKEND_BASE_URL=https://…onrender.com`（正確な値は ENV.md / Render の設定を見る）
- 将来: 独自ドメイン `https://meguribi.com` を取得したら  
  - `https://meguribi.com/api/...` でフロント → バックエンド通信を統一する想定

フロント（Next.js）側では、基本的に

- `NEXT_PUBLIC_BACKEND_URL`（ブラウザ側で直接叩く場合）
- `BACKEND_BASE_URL`（Next.js 内 API ルートからサーバー側で叩く場合）

のどちらかを使ってリクエストを組み立てる。

### 0-2. 共通仕様

- すべて **JSON** を返す
- タイムスタンプは原則 **ISO8601 + タイムゾーン付き**  
  例: `"2025-11-20T21:15:00+09:00"`
- `ok` フラグを必ず含める
  - 正常: `{ "ok": true,  ... }`
  - 異常: `{ "ok": false, "error": "human_readable_message", "detail": "開発者向け補足（任意）" }`
- 文字コード: UTF-8
- タイムゾーン:
  - データは基本 `Asia/Tokyo`
  - 将来、海外店舗が増えたら `store.timezone` に従って扱う

### 0-3. ストア（店舗）識別子

現状:

- `store`（クエリパラメータ）として **スラッグ文字列** を使う
  - 例: `store=nagasaki`
- 2025-11 時点で Next.js 側の型定義は以下のイメージ

  ```ts
  type StoreId = "nagasaki"; // 将来 "shibuya", "shinjuku" … を追加
今後:

Supabase の stores テーブルに id（数値 or UUID）もあるが、
フロント側からは当面 スラッグ（文字列） を使う想定。

API レベルでは以下のポリシーにする:

クエリパラメータ: store（スラッグ、必須 or デフォルト nagasaki）

レスポンス JSON: store（スラッグ）と store_id（数値 or UUID）の両方を持たせる方向で準備

1. 公開 API（フロントエンドが使う）
1-1. ヘルスチェック
エンドポイント
GET /healthz

目的
Render, ローカルの監視・スモークテスト用

外部の監視サービス（将来導入を検討）からも叩きやすいようにシンプルに

リクエスト
パラメータなし

レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "service": "meguribi-backend",
  "version": "0.1.0",
  "time": "2025-11-22T10:15:00+09:00"
}
1-2. メタ情報取得
エンドポイント
GET /api/meta

目的
ダッシュボード初期表示時に、店舗や時間帯などの「設定情報」を取得する

将来、複数店舗・複数ブランドになってもここを見れば UI 側が自動で調整できるようにする

クエリパラメータ
名前	型	必須	説明
store	string	任意	店舗スラッグ。未指定なら現状は nagasaki を想定。

レスポンス（イメージ）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "store_slug": "nagasaki",
  "store_id": 1,
  "timezone": "Asia/Tokyo",
  "window": {
    "start": 19,
    "end": 5
  },
  "forecast": {
    "freq_min": 15,
    "model": "xgboost",
    "allow_missing_weather": true
  },
  "features": {
    "supabase_primary": true,
    "google_sheet_backup": true,
    "multi_store_enabled": false
  }
}
1-3. 実測データレンジ取得
エンドポイント
GET /api/range

目的
店舗 × 日付レンジの 実測データ（男女人数＋天気など） を取得

ダッシュボードの「今日の推移グラフ」「過去データ閲覧」などで利用

典型的な呼び出し
GET {{BASE}}/api/range?limit=0
→ メタ情報のみ（データなし）

GET {{BASE}}/api/range?limit=120000
→ ほぼ全期間のデータをまとめて取得（ローカル検証用）

クエリパラメータ（案）
名前	型	必須	説明
store	string	任意	店舗スラッグ。未指定なら nagasaki を使う。
from	string	任意	開始日時（ISO8601 / 日付のみも可）。未指定なら一番古いデータ。
to	string	任意	終了日時（ISO8601 / 日付のみも可）。未指定なら現在時刻。
limit	int	任意	返す最大件数。0 の場合は「メタ情報だけ返すモード」として利用。
order	string	任意	"asc" / "desc"。未指定なら "asc"。
tz	string	任意	タイムゾーン文字列。未指定なら Asia/Tokyo。

レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "store_slug": "nagasaki",
  "timezone": "Asia/Tokyo",
  "data": [
    {
      "ts": "2025-11-20T21:15:00+09:00",
      "men": 12,
      "women": 10,
      "total": 22,
      "weather_code": 61,
      "temp_c": 14.2,
      "rain_mm": 0.5,
      "source": "supabase"
    }
  ]
}
source は "supabase" / "google_sheet" など、どこから取ってきたかを表すためのフィールド（当面は任意）

1-4. 日次サマリー取得
エンドポイント
GET /api/summary

目的
1 日単位の集計値（最大人数、平均人数、ピーク時間帯など）を出す。

将来的には「この店の傾向」「曜日ごとの込み具合」などの分析にも使う。

クエリパラメータ
名前	型	必須	説明
store	string	任意	店舗スラッグ。未指定なら nagasaki。
date	string	任意	YYYY-MM-DD。未指定なら「今日」のサマリーを返す。

レスポンス（イメージ）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "date": "2025-11-20",
  "timezone": "Asia/Tokyo",
  "stats": {
    "max_total": 78,
    "max_total_time": "2025-11-20T22:30:00+09:00",
    "avg_total": 35.4,
    "open_samples": 32,
    "male_peak": 44,
    "female_peak": 40
  }
}
※ 実装側では、stats の中身が多少変わっても良いが、キーを消すときは互換性に注意。

1-5. 今から 1 時間の予測
エンドポイント
GET /api/forecast_next_hour

目的
「今から 1 時間」 の男女人数を 15 分刻み（仮）で予測する。

ダッシュボードの「今から 1 時間」の小さなグラフに使う。

クエリパラメータ
名前	型	必須	説明
store	string	任意	店舗スラッグ。未指定なら nagasaki。

レスポンス型（Next.js 側と合わせる）
ts
コードをコピーする
type ForecastPoint = {
  ts: string;        // 予測対象の時刻
  men_pred: number;  // 男性人数予測
  women_pred: number;// 女性人数予測
  total_pred: number;// 合計人数予測
};
レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "freq_min": 15,
  "data": [
    {
      "ts": "2025-11-20T21:15:00+09:00",
      "men_pred": 10.2,
      "women_pred": 8.5,
      "total_pred": 18.7
    },
    {
      "ts": "2025-11-20T21:30:00+09:00",
      "men_pred": 11.3,
      "women_pred": 9.1,
      "total_pred": 20.4
    }
  ]
}
1-6. 今日の夜の予測（残り時間）
エンドポイント
GET /api/forecast_today

目的
「今日の夜（例: 19:00〜翌 05:00）」の残り時間帯の予測をまとめて返す。

ダッシュボードのメイン予測グラフ（帯付きチャート）用。

クエリパラメータ
名前	型	必須	説明
store	string	任意	店舗スラッグ。未指定なら nagasaki。

レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "freq_min": 15,
  "window": {
    "start": "2025-11-20T19:00:00+09:00",
    "end": "2025-11-21T05:00:00+09:00"
  },
  "data": [
    {
      "ts": "2025-11-20T21:15:00+09:00",
      "men_pred": 10.2,
      "women_pred": 8.5,
      "total_pred": 18.7
    }
  ]
}
将来的に

予測バンド（p10, p50, p90）や

信頼区間の上下

などを追加したくなったら、data 内にフィールドを足していく方針。

1-7. 店舗一覧
エンドポイント
GET /api/stores/list

目的
フロント側で「店舗の選択 UI」「近くのお店一覧」などを出すための基本情報取得。

今後、二次会候補 や ブランド別表示 などもここから紐付けていく。

クエリパラメータ
現状なし（後で brand や pref などを追加してもよい）

レスポンス（イメージ）
json
コードをコピーする
{
  "ok": true,
  "stores": [
    {
      "id": 1,
      "slug": "nagasaki",
      "name": "オリエンタルラウンジ 長崎店",
      "brand": "oriental_lounge",
      "lat": 32.744,
      "lng": 129.872,
      "timezone": "Asia/Tokyo",
      "open_time": "19:00",
      "close_time": "05:00",
      "is_active": true
    }
  ]
}
1-8. ヒートマップ用データ（将来・案）
エンドポイント
GET /api/heatmap

目的
「時間 × 曜日」などのヒートマップを描画するためのサマリーデータを返す。

まだ UI 側が決まりきっていないので 仕様は仮。

将来実装する際のイメージだけ記載しておく。

クエリパラメータ案
名前	型	必須	説明
store	string	任意	店舗スラッグ。
period	string	任意	"3m", "6m", "1y" などの集計期間指定。

レスポンス案
json
コードをコピーする
{
  "ok": true,
  "rows": [
    {
      "weekday": 5,
      "hour": 22,
      "avg_total": 64.2
    }
  ]
}
2. 内部 API（Cron / バッチ用）
ここは 外部公開しない前提 のエンドポイント群。
Render 側の cron-job.org や、将来予定している「ローカルバッチ」から叩く。

2-1. 単店舗収集（旧仕様）
エンドポイント
POST /tasks/collect

目的
旧仕様として存在していた「単一店舗の人数を公式サイトから取得し、ログに追記する」タスク。

今後は基本的に マルチ店舗対応のタスクに置き換えていく 想定だが、
既存のスクリプトが使っている可能性を考慮して残しておく。

リクエスト
ボディ: 原則なし（将来 {"store": "nagasaki"} を許容しても良い）

レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "store": "長崎店",
  "inserted": 1,
  "ts": "2025-11-20T21:15:00+09:00",
  "source": "oriental_official_site"
}
2-2. マルチ店舗収集（新仕様 / 想定）
※ コード側には tasks_multi_collect のような関数名が存在するため、
エンドポイントは以下のどれかで実装されている想定。
実装を確認してから、ここを正とすること。

候補: POST /tasks/multi_collect or POST /tasks/collect_all

目的
登録済みの全店舗（例: オリエンタルラウンジ 38 店舗）を一括で収集し、
Supabase の logs テーブルへ保存する。

リクエスト
ボディ: 通常は空

将来、{"brand": "oriental_lounge"} などフィルタ指定を追加してもよい

レスポンス（イメージ）
json
コードをコピーする
{
  "ok": true,
  "stores": [
    { "store": "nagasaki", "inserted": 1, "status": "ok" },
    { "store": "shibuya", "inserted": 1, "status": "ok" }
  ]
}
2-3. tick エンドポイント（Cron の入口にしたい）
エンドポイント案
POST /tasks/tick

目的
外部の Cron サービスからは この 1 本だけ叩く 形にして、
中で

マルチ店舗収集

将来の学習・モデル更新

メンテナンス処理

などを順番に呼び出す「オーケストレーター」にする。

リクエスト
ボディ: 原則なし

認証: X-CRON-TOKEN のようなヘッダを設ける余地あり（ENV で設定）

レスポンス（例）
json
コードをコピーする
{
  "ok": true,
  "tasks": {
    "multi_collect": { "ok": true, "stores": 38 },
    "forecast_refresh": { "ok": true }
  }
}
3. 今後検討する API（メモ）
将来追加しそうなものだけ、ラフにメモしておく。

3-1. 近くの二次会候補 API
GET /api/nearby_second_places

目的:

UI で見えている「近くのお店（カラオケ・ダーツ・ホテル・ラーメンなど）」を返す。

Google Places API などの外部サービスを使う場合、ここでラップする。

クエリ案:

store（基準店舗スラッグ）

categories（"karaoke,bar,hotel,ramen" などカンマ区切り）

radius_m（検索半径）

レスポンス案:

json
コードをコピーする
{
  "ok": true,
  "base_store": "nagasaki",
  "places": [
    {
      "name": "Bar Night Owl",
      "category": "bar",
      "distance_m": 190,
      "open_until": "02:00",
      "rating": 4.3,
      "review_count": 64,
      "lat": 32.7441,
      "lng": 129.8723
    }
  ]
}
3-2. 通知 / PWA 登録 API
POST /api/notifications/register

目的:

iPhone / Android で ホーム画面アイコンから開ける PWA を作り、
Web Push / ローカル通知の設定情報を保存する。

ざっくり案:

json
コードをコピーする
{
  "ok": true,
  "subscription_id": "xxxx"
}
実際の実装時には、Service Worker や Push API の仕様に合わせて再設計する。

4. エラーハンドリング・バージョニング方針
重大な Breaking Change を入れる場合は、できるだけ

旧キーはしばらく残す（非推奨フラグを立てる）

新キーを追加する形で移行

どうしても難しい場合のみ、/api/v2/... を切る

フロント側では

ok === false の場合は「やさしいエラーメッセージ」を表示

error フィールドの中身はユーザーにはそのまま出さず、
ログや開発者用表示に回す

5. テスト方法（VS Code REST Client）
plan/requests.http に代表的なリクエストをまとめている。

本番 Render の疎通確認

ローカル Flask の動作確認

新しいエンドポイントを追加したときのスモーク

などは、まずここに 1 行追加してから実験する。

以上が、2025-11 時点での めぐりび / MEGRIBI API コントラクト最新版。
エンドポイントを増やしたり、レスポンスの形を変えたときは このファイルから必ず更新 していく。