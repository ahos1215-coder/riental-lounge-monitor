めぐりび / MEGRIBI — CRON & Scheduled Jobs 設計

最終更新: 2025-11-23
対象ブランチ: main
対象コミット: zip 内 .git/refs/heads/main（ユーザー環境の最新版）

このドキュメントは、めぐりび / MEGRIBI で使う「時間ベースの処理（CRON / スケジュール実行）」を一箇所にまとめた設計メモです。
「どのタイミングで」「どの URL を」「どのぐらいの頻度で」「誰が（どのサービスが）」叩いているかをここで定義します。

0. このドキュメントの目的

ChatGPT / 将来の自分 / 他の開発者が、

データ収集

予測更新

バッチ処理（バックアップや再学習など、今後追加するものを含む）
をどのスケジューラから、どのエンドポイントで実行しているかをすぐに把握できるようにする。

「Supabase 一本化」「複数店舗対応」「PWA での Web 通知」など、今後の拡張と整合が取れるように、

現在動いているもの

近い将来追加予定のもの
を区別して書いておく。

1. 前提と用語
1-1. 環境

ローカル開発環境

Windows 11 + VS Code + Python（Flask バックエンドを app.py or wsgi.py で起動）

CRON は基本的に「手動実行」で代用（ブラウザ or curl）。

本番環境

Render（Python / Flask の Web サービス）

Supabase（PostgreSQL + 認証 + 将来的な Edge Functions）

フロントエンド: Next.js 16（Render or 別ホスティング）

スケジューラ

現状の本番では cron-job.org を使用。

将来的には

Supabase Edge Functions + Supabase のスケジュール機能

もしくは別のマネージドスケジューラ
への移行も検討余地あり（ただし現時点では cron-job.org 継続前提）。

1-2. タイムゾーン

すべての時間に関する前提は Asia/Tokyo（JST）。

cron-job.org 側のタイムゾーンも 必ず Asia/Tokyo に合わせる。

1-3. 実行対象のざっくり分類

データ収集 + Supabase への書き込み

例: 5 分おきに 38 店舗分の男女人数と天気をスクレイピングして logs テーブルへ。

予測（Forecast）の更新

例: 一定間隔で XGBoost / 将来的には LightGBM で予測を更新。

メンテナンス / バックアップ / 再学習

今はほぼ手動 or Supabase 自動バックアップに依存。
今後、定期タスクとして整理する予定。

通知（将来）

LINE 通知は課金が発生するため一旦保留。

将来は「ホーム画面に追加された iPhone / Android の PWA に対して Web Push」を検討中。
そのタイミングで「毎日 18:00 に通知を送る」ような CRON が増える想定。

2. 現在の本番 CRON 一覧（2025-11 時点）

2025-11 時点で、実際に運用する前提になっている CRON は 1 本だけです。

ID	ジョブ名	用途	URL（パス）	スケジューラ	間隔	ステータス
J1	collect_and_forecast_prod	38 店舗分のデータ収集 + 予測更新のトリガー	https://<RENDER_BASE_URL>/tasks/tick	cron-job.org	5 分ごと	運用対象

<RENDER_BASE_URL> は Render 側の URL（例: https://meguribi.onrender.com）に読み替え。

今後追加を想定しているが、まだ存在しないジョブも先に名前だけ定義しておきます（詳細は後述）。

ID	ジョブ名	想定用途	ステータス
J2	daily_supabase_backup_check	Supabase の自動バックアップ / Retention を確認するための「状態チェック」用（Slack / ログ出力など）	未実装
J3	weekly_model_retrain	週 1 回、ローカル or 一時ワーカーで予測モデルを再学習するトリガー	未実装
J4	evening_push_summary	将来の PWA / Web Push 向け「今日の混雑状況まとめ通知」送信用トリガー	未実装
3. 実運用しているジョブ: collect_and_forecast_prod（J1）
3-1. 役割のイメージ

このジョブは、

38 店舗分の最新データをまとめて取得する（スクレイピング or API）

Supabase の logs テーブルに保存する

オプションで 予測値の更新 を行う

ための「トリガー」で、1 本叩けば全店舗分をループして処理する設計にしてあります。

そのため、店舗が増えても

cron-job.org 側のジョブは 1 本のまま

コードの中で stores テーブルや stores.json を見てループを増やす
という運用になります。

将来的に 相席屋 / JIS を追加しても、基本的には同じ 1 ジョブで回せる想定です。

3-2. 外部スケジューラ（cron-job.org）の設定

cron-job.org 上では概ね以下のように設定する想定です。

ログインして「Create cronjob」を押す

設定値の例

Name: MEGRIBI collect+forecast (prod)

URL: https://<RENDER_BASE_URL>/tasks/tick

HTTP Method: GET（特別なボディ送信は不要）

Schedule:

Every: 5 minutes

もしくは「19:00〜05:00 の間だけ」動かすようなルールにする（細かい時間指定はお好み）

夜間だけ動かすかどうか

アプリ側には NIGHT_START_H, NIGHT_END_H, FORECAST_FREQ_MIN などの環境変数があります。

NIGHT_START_H（例: 19）

NIGHT_END_H（例: 5）

FORECAST_FREQ_MIN（例: 15）

アプリ側で「時間帯チェック」をしているため、cron-job.org は 24 時間 5 分ごとでも構わない設計にしています。

cron-job.org 側は簡単に「5 分ごと」で設定

実際に「集計・予測する時間」はアプリ内で制御
（夜以外の時間帯は「何もせず即 return」する）

こうしておくと、「営業時間の変更」「夜の範囲の調整」を環境変数だけで変えられるため、スケジューラ側の設定を毎回いじらずに済みます。

3-3. /tasks/tick 実行時の裏側の流れ（概念）

実装は app/multi_collect.py や oriental/routes/tasks.py あたりに存在している想定で、
/tasks/tick が呼ばれたときに、ざっくり以下の流れになります。

時間帯チェック

現在時刻（Asia/Tokyo）を取得。

NIGHT_START_H〜NIGHT_END_H の範囲内かを確認。

範囲外なら「何もしない or 軽いログだけ残して終了」。

対象店舗リストの取得

38 店舗分の店舗一覧を

data/stores.json
または

Supabase の stores テーブル
から取得する。

各店舗には store_id, name, brand, pref, scraping_url などが紐づいている想定。

マルチ店舗収集処理（multi_collect）

ループしながら店舗ごとに

対象サイトの HTML を取得（スクレイピング）

男性 / 女性 / 合計人数をパース

同じタイムスタンプで、天気情報（降水量 / 気温 / 天気コードなど）も付与
（天気は別モジュールや API を呼んでいる想定、Supabase 化に向けて共通化中）

1 店舗ごとに「1 行のレコード」を組み立てる。

ts（タイムスタンプ）

store_id

men, women, total

weather_* 一式

その他フラグ（is_trial, source など）

Supabase への保存

今後の方針としては、Google スプレッドシートはほぼ使わず Supabase 一本化。

そのため、組み上がったレコードは

Supabase の logs テーブルへ insert

将来的に logs_aggregated などの集計テーブルへも書き込む可能性あり。

旧来パスとして、

ENABLE_GSHEET / ENABLE_GAS のようなフラグが有効なら

GAS 経由で Google スプレッドシートにも二重書き込みする経路が残っているかもしれないが、
今後はデフォルト OFF にする前提。

予測の更新（オプション）

ENABLE_FORECAST=1 の場合のみ

直近 N 時間分のデータを読み直して

次の 1 時間 or 数ポイント分の予測を更新。

予測結果は

既存アーキ: artifacts/ ディレクトリや oriental/data/ 内の JSON / pickle

将来的: Supabase の forecasts テーブル
に保存して、Next.js フロントから参照できるようにする。

レスポンス

/tasks/tick のレスポンス例（概念）:

{
  "ok": true,
  "stores": 38,
  "inserted_rows": 38,
  "forecast_updated": true
}


cron-job.org 側ではレスポンスは特に使わず、「200 が返ってくるかどうか」ぐらいだけ見る想定。

3-4. 動作確認のやり方

一時的にブラウザ or curl から /tasks/tick を叩く

ローカル:

$env:ENABLE_FORECAST="1"
flask run  # or python app.py

curl.exe -s "http://localhost:5000/tasks/tick" | python -m json.tool


本番（Render）:

curl.exe -s "https://<RENDER_BASE_URL>/tasks/tick" | python -m json.tool


Supabase の logs テーブルを確認

直近のタイムスタンプで 38 行（店舗数分）のデータが増えているかをチェック。

store_id や brand が意図通り入っているかも確認。

Next.js 側のグラフ表示

「今から 1 時間の予測」グラフに最新値が反映されるかを見る。

反映されない場合は

バックエンドの /api/range レスポンス

Next.js の fetch 処理
を合わせて確認する。

4. まだ実装していないが、想定しているジョブ

この章は「今は存在しないが将来追加したい CRON / スケジュール処理」をまとめておくメモです。
ROADMAP.md とリンクする形で「どのタイミングで実現するか」を後から決められるようにします。

4-1. J2: daily_supabase_backup_check（バックアップ状態の監視）

目的

Supabase は自動バックアップを提供しているが、

それが正常に動いているか

保持期間が足りているか
を週 1〜数日に 1 回、人間の目で確認できるようにする。

実現イメージ

簡易的には「 Supabase ダッシュボードを手で見る」で十分。

将来的には

Edge Functions or 別サーバから Supabase のメタ情報を叩き

Slack / Discord に「バックアップ OK / 残り保持期間」などのメッセージを送る。

ステータス

2025-11 現在は 未実装。

CRON.md では「作るならこの名前で」というメモだけ残している状態。

4-2. J3: weekly_model_retrain（予測モデルの再学習）

目的

「3 ヶ月後に精度を上げたいわけではない」という方針に合わせ、

手間のかかることは極力避けつつ、

週 1 回程度の再学習で「少しずつ賢くしていく」。

現状

ローカル PC で必要なときに手動で再学習するイメージ。

python oriental/ml/train_local.py のようなスクリプトを手で叩く。

将来のオートメーション案

方法 A: Windows タスクスケジューラで、毎週日曜の朝 6:00 に再学習スクリプトを叩く。

方法 B: 一時的なクラウドワーカー（Render の Background Worker や別のサービス）で週 1 回実行。

注意

ローカルモデルか、グローバルモデルか

都心と地方で傾向が違うので、できれば「ローカル（店舗 / エリアごと）モデル」を維持したい。

モデルの出力先

旧来: artifacts/ ディレクトリに pickle / JSON を保存。

将来: Supabase の models テーブルや forecasts テーブルにメタ情報を持たせる案もあり。

4-3. J4: evening_push_summary（PWA / Web Push のための夕方通知）

背景

LINE 通知はメッセージ数に応じて課金が発生するため、現時点では採用しない方針。

代わりに「iPhone/Android のホーム画面に追加された Web アプリ（PWA）」に対して
無料の Web Push 通知を送りたい、という方向性。

想定機能

毎日 18:00 頃に

「今夜混みそうな店舗 3 選」

「自分の地域の男女比が良さそうな店」
などをまとめたメッセージを作成し、

Web Push のエンドポイントに送る。

CRON との関係

18:00 に

https://<RENDER_BASE_URL>/tasks/push-evening-summary
を叩くジョブを 1 本増やすイメージ。

そのエンドポイント内で

Supabase から最新のログ / 予測を集計

Push 対象ユーザーのトークン一覧を取得

各ユーザーに対して Push を送信
という流れ。

ステータス

現時点では構想レベル。
ONBOARDING / ARCHITECTURE にも「Web Push / PWA の構想」として言及済み。

5. 複数店舗・複数ブランドになったときの CRON 方針

「複数店舗対応」「Supabase 一本化」「将来的に複数ブランド（相席屋 / JIS）」を見越した CRON の基本方針は以下です。

CRON の本数は増やさない

できるだけ

データ収集用: 1 ジョブ

通知用: 1 ジョブ（将来）

のように、最小限のジョブ数に抑える。

どの店舗を対象にするかは、コード側で決める

stores テーブル（Supabase） or stores.json に

brand

prefecture

enable_collect（収集有効フラグ）

などを持たせ、

CRON は「すべてを一旦叩く」

どの店舗を実際に処理するかはアプリ側が決定
という設計にする。

夜の時間帯は環境変数で制御

「将来、営業時間が変わっても CRON を触りたくない」ので、

NIGHT_START_H

NIGHT_END_H

を変えるだけで反映されるようにしておく。

スケジューラの種類も徐々に移行可能な書き方にしておく

今は cron-job.org。

将来 Supabase のスケジュール機能や別サービスに移したくなったとき、

「とにかく /tasks/tick を 5 分ごとに叩けば良い」
というインターフェースを守っていれば、移行コストは低くなる。

6. まとめ

現状、本番で実際に使う前提の CRON は 1 本（J1: /tasks/tick）だけ。

この 1 本で

38 店舗（将来は相席屋 / JIS を含めた全店舗）の

データ収集

Supabase への保存

予測更新
までをトリガーする設計になっている。

Google スプレッドシートは「バックアップ / 非常用」としては残すかもしれないが、

データの正本（Single Source of Truth）は Supabase に寄せていく方針。

今後は

週 1 回程度の再学習（J3）

PWA / Web Push の夕方通知（J4）
などを追加していく可能性があり、そのときはこの CRON.md を更新して「何が増えたか」を明示していく。

この時点での状態を前提に、次の ChatGPT / 将来の自分は

「とりあえず 5 分ごとの /tasks/tick さえ守れば最低限の動きは担保される」

「新しいジョブを増やしたら、ここに追記すれば全体像が壊れない」

という基準で作業を進めることができます。