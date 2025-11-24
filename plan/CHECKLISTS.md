# CHECKLISTS.md — めぐりび / MEGRIBI 運用・リリース・障害対応チェックリスト

最終更新: 2025-11-22 (ChatGPT Web / plan refresh)  
対象:  
- Flask バックエンド (`riental-lounge-monitor-main/`)  
- multi_collect.py（38店舗スクレイピング → Supabase logs）  
- Next.js フロントエンド (`frontend/`)  
- 将来: 近くの二次会候補 UI / Web プッシュ通知（PWA）

> このファイルは「毎日・毎週・リリース前後・障害時に何を確認すればいいか」を  
> 一覧にしたチェックリストです。  
> 細かい手順は `RUNBOOK.md`、環境変数は `ENV.md` を参照してください。

---

## 1. デイリー運用チェック

### 1-1. バックエンド / データ収集

- [ ] cron-job.org の `collect_5min`（仮称）が **Enable** になっている  
  - URL: `https://riental-lounge-monitor.onrender.com/tasks/collect`  
  - 間隔: 5分  
  - 実行時間帯: 19:00〜翌 05:00（JST）想定  
- [ ] Render Logs に `collect_all_once.start` / `collect_all_once.success` が出ている  
  - 1晩につき「成功ログ」が一定数（19〜5時 × 5分間隔）出ていること  
  - 例外スタックトレース（ERROR）は出ていないこと  
- [ ] Supabase ダッシュボードで `logs` テーブルに **昨夜分の行が増えている**  
  - `ts` の日付・時刻が日本時間の夜〜深夜帯になっている  
  - `src_brand="oriental"` で 38 店舗ぶんのレコードが入っていそうか目視確認  

### 1-2. 旧 Google スプレッドシート（当面サブ・バックアップ扱い）

- [ ] 当面は「大きなトラブル時のバックアップ」想定なので、基本は確認不要  
- [ ] ただし ML / 予測がシート前提な間は、以下もたまに見る  
  - [ ] GAS 経由の Sheet に **日付が進んでいるか**  
  - [ ] 明らかな欠損（日付が飛んでいる日）がないか  

### 1-3. フロントエンド（Next.js ダッシュボード）

- [ ] 本番 URL（Render 経由のフロント or ローカル開発）でトップページが開く  
- [ ] 当日の来店状況グラフが描画される（最低限、エラー画面になっていない）  
- [ ] 予測チャート（Next Hour / Today）が有効化済みなら、グラフが表示される  

※ 「近くの二次会候補」「Web 通知」機能は実装後に  
　ここに確認項目を追加する想定。

---

## 2. リリース前チェック（バックエンド）

### 2-1. コード品質・テスト

- [ ] 仮想環境有効化済み（例: `.venv`）  
- [ ] 依存インストール済み: `pip install -r requirements.txt`  
- [ ] 構文チェック: `python -m compileall .` がエラーなし  
- [ ] 既存テストがあれば `pytest -q` がグリーン  
- [ ] `plan/API_CONTRACT.md` の仕様とコードの乖離がないか軽く目視  

### 2-2. 環境変数・設定

- [ ] `ENV.md` に書いてある必須環境変数が Render の Environment に設定されている  
  - BACKEND 基本: `TIMEZONE`, `LOG_LEVEL`, `WINDOW_START`, `WINDOW_END`, `MAX_RANGE_LIMIT` 等  
  - multi_collect 用: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ENABLE_WEATHER`, `BETWEEN_STORES_SEC` 等  
  - ML / 予測用: `GS_READ_URL`（当面）  
- [ ] テスト用に、一時的に **危険な値** を入れていない  
  - 例: `MAX_RANGE_LIMIT` を極端に大きくしたままにしていない  
  - デバッグ用の `print` / ログ出力を残しすぎていない  

### 2-3. デプロイ対象の確認

- [ ] 変更ファイルに `plan/*.md` の更新が含まれている（必要な場合）  
- [ ] multi_collect / forecast / routes まわりの差分内容をざっと確認  
- [ ] 本番 Render サービスの Auto Deploy 対象ブランチが `main` である  

---

## 3. リリース後チェック（バックエンド）

### 3-1. スモークテスト（API）

PowerShell 例（URL は実環境に合わせて調整）:

- [ ] `/healthz`  
  ```powershell
  curl.exe -s https://riental-lounge-monitor.onrender.com/healthz | python -m json.tool
 /api/range（極端な limit を投げてクランプ確認）

powershell
コードをコピーする
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/range?from=2024-11-01&to=2024-11-02&limit=120000" | python -m json.tool
期待: HTTP 200

Logs に api_range.success ... limit=<MAX_RANGE_LIMIT> が出ている

 予測 API（有効時）

powershell
コードをコピーする
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/forecast_next_hour?store=nagasaki" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/forecast_today?store=nagasaki" | python -m json.tool
3-2. Supabase / multi_collect
 Render Logs: collect_all_once.start → collect_all_once.success stores=38 が出ている

 Supabase logs テーブルに当日分のレコードが新規追加されている

デプロイ直後〜その夜の「最初の数実行」が成功しているかを確認

3-3. フロントエンド
 トップページにアクセスし、エラーが出ていない

 来店グラフ・予測グラフが想定どおりに表示される

 （実装済みなら）

近くの二次会候補リスト（カラオケ・ダーツ・ホテル・ラーメンなど）が表示される

「店舗の位置情報」や「二次会リンク」が変な場所を指していない

4. 障害対応チェックリスト
4-1. 「データが増えていない / グラフが空」の場合
 Supabase logs テーブルの最新行をチェック

昨夜以降レコードが増えていない → multi_collect または cron-job.org の問題

 cron-job.org

対象ジョブの History / Logs を確認

連続で 4xx / 5xx が出ていないか

「execution of the cronjob fails」通知が来ていないか

 Render Logs

collect_all_once.failed が出ていないか

直近デプロイ後に例外が増えていないか

 一時回避

必要に応じて、ローカルから python multi_collect.py を手動実行し Supabase に流し込む

その上で、原因がコード側か外部要因かを切り分ける

4-2. 「/api/range が 5xx / 422」の場合
 /healthz が 200 かどうか確認

 Render Logs の api_range.validation_error / api_range.upstream_error を確認

パラメータ逆転（from > to）で 422 になっていないか

GAS / Google Sheets への接続で 502 を返していないか

 一時回避

期間を短くして再リクエストしてみる

どうしてもダメな場合は /api/meta, /api/summary などスタブ API と組み合わせて
「最低限の画面だけでも出す」運用に切り替える

4-3. 「予測 API が空配列を返す / エラー」の場合
 Render Logs の forecast.service.* ログを確認

forecast.service.history size=0 → 学習用データが取得できていない

forecast.provider.remote_failed → GS_READ_URL かシート側の問題

 一時回避

フロント側で「予測なし（準備中）」と表示するガードを入れる

バックエンドに無理に手を入れず、落ち着いてから学習・データ供給を見直す

5. 月次・定期メンテナンス
5-1. 依存関係・セキュリティ
 requirements.txt の依存バージョンを確認し、月1回程度アップデート検討

 python -m compileall . / pytest -q を回してからデプロイ

 不要になったデバッグログ / print を削除

5-2. Supabase とログ肥大化対策
 Supabase logs テーブルのレコード件数を確認

 必要なら

古いデータを別テーブルにアーカイブ

集計用ビュー・マテリアライズドビューを追加する検討

5-3. Google スプレッドシート（バックアップ）
 一応まだデータが増え続けているか確認（停止していても「想定どおり」ならメモ）

 将来、完全廃止するか「月1回だけバックアップとして流す」か方針を整理

5-4. ドキュメント / 設計
 ONBOARDING.md, ARCHITECTURE.md, ROADMAP.md, RUNBOOK.md, ENV.md をざっと読み、
実装と乖離していないか確認

 大きく変わった場合は本ファイル（CHECKLISTS.md）も更新

5-5. UI / 通知（構想段階〜実装後）
 近くの二次会候補 UI

カラオケ・ダーツ・ホテル・ラーメンなどの情報ソースが生きているか

表示内容が古くなっていないか（営業時間・閉店など）

 Web プッシュ通知 / PWA

iPhone の「ホーム画面に追加」＋ Web 通知設定が想定どおり動いているか

通知が多すぎてウザくなっていないか（頻度・文言を見直す）

6. 大きな仕様変更時のメモ
 「Supabase ログ前提で /api/range も Supabase から読む」ような
重要な仕様変更を入れるときは、必ず以下を更新する

ARCHITECTURE.md（データフロー図・説明）

API_CONTRACT.md（どの API がどのストアを読んでいるか）

RUNBOOK.md（運用手順）

ENV.md（必要な環境変数）

本ファイル（CHECKLISTS.md）