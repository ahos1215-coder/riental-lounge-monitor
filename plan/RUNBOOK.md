# RUNBOOK
Last updated: 2026-03-30 (Round 9 整合)
Target commit: (see git)

ローカル起動・本番メモ・**初回オンボーディング**・**定期処理（cron）**・トラブルシュート。  
（旧 `ONBOARDING.md` / `CRON.md` をここに統合）

---

## 初回オンボーディング（本番の心構え）

### Backend（Render / Flask）
- 常時起動想定。`DATA_BACKEND=supabase`。
- 環境変数例: `BACKEND_URL`（フロントから参照）、`SUPABASE_*`、`ENABLE_FORECAST`、`STORE_ID`、`MAX_RANGE_LIMIT=50000`（`plan/ENV.md`）。
- デプロイ後、`/tasks/tick` が一定間隔で動く構成があり得る（夜間も収集）。`ENABLE_FORECAST=1` のときのみ予測更新。

### Frontend（Vercel / Next.js 16）
- GitHub 連携 → main push でデプロイ。
- `BACKEND_URL` を Render の API に向ける。ブラウザから Supabase 直はしない。
- `useSearchParams` は `Suspense` 配下。Recharts Tooltip は型を拡張してビルド通過。

### LINE 下書き（本番）
- Messaging API の Webhook を **Vercel の `POST /api/line`** に。**n8n は使わない。**
- `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `GEMINI_API_KEY` / Supabase service role（`blog_drafts`）等は `plan/ENV.md`。
- **レート制限**: 悪用・誤爆で Gemini／バックエンド負荷が跳ねないよう、`UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`（Upstash）を本番で設定することを推奨。**未設定時はメモリ内フォールバックとなり、サーバレス環境では実効性が弱くなる**。詳細は `plan/ENV.md` の LINE 節。

### OGP・シェア用 URL（本番）
- `metadataBase` と SNS 用メタデータは **`NEXT_PUBLIC_SITE_URL`**（または `NEXT_PUBLIC_BASE_URL`）が揃っていると正しい canonical / `og:url` になる。未設定だとビルド時の `VERCEL_URL` や `localhost` に寄る。
- 既定の共有用画像は `frontend/src/app/opengraph-image.tsx`（動的 OG 画像）。

### Night window / 二次会 / Supabase
- 店舗 UI の夜 19:00–05:00 は **`useStorePreviewData.ts`**。LINE 下書きの窓は **`insightFromRange.ts`**。
- 二次会は **map-link**（`plan/SECOND_VENUES.md`）。
- `blog_drafts` は Next サーバー API のみが書き込み（service role）。

---

## Local Development

### Backend (Flask)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# .env に必要な環境変数を設定（plan/ENV.md 参照）
python app.py
```

### Frontend (Next.js)
```
cd frontend
npm install
# .env.local（ルート or frontend）— plan/ENV.md 参照
npm run dev
```

### 動作確認（ローカル）
- UI: `http://localhost:3000/?store=nagasaki` など
- 生データ: `http://127.0.0.1:5000/api/range?store=nagasaki&limit=400`

#### LINE 下書き・定時 Cron（ローカル）
1. Flask を起動（`BACKEND_URL` が `http://127.0.0.1:5000` になるよう `.env.local` を確認）
2. `frontend` で `npm run dev`
3. **LINE Webhook**: `.env.local` に `SKIP_LINE_SIGNATURE_VERIFY=1` を入れ、**`npm run dev`（`NODE_ENV=development`）**で `POST http://localhost:3000/api/line` に LINE 形式の JSON を送る（`scripts/dev/smoke-requests.http` 参照）。本番では署名スキップは無効（`plan/ENV.md`）。
4. **定時 Cron 相当**: `.env.local` に `SKIP_CRON_AUTH=1`（development のみ）を入れ、`GET http://localhost:3000/api/cron/blog-draft` を叩く。または `CRON_SECRET=test` と `Authorization: Bearer test` で叩く
5. Supabase を使う場合は `SUPABASE_*` と `GEMINI_API_KEY` を設定し、`blog_drafts` に行が増えることを確認
6. **自動スモーク（推奨）**: 別ターミナルで `cd frontend` のうえ  
   - `npm run smoke:blog-apis -- --quick` … `GET /api/line` と Cron の **401**（未認証）のみ  
   - `npm run smoke:blog-apis` … 上記に加え、`.env.local` の **`CRON_SECRET`**（Bearer）または **`SKIP_CRON_AUTH=1`** 時に **フル Cron**（Backend + Gemini + DB。最大約2分）

---

## Local Checks
- `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- `/api/forecast_today?store=...`（`ENABLE_FORECAST=1` のとき）
- `/insights/weekly` が `index.json` を読めること
- LINE 下書き試験: `GET http://localhost:3000/api/line` がヘルス相当。`POST /api/line` は **development** で `SKIP_LINE_SIGNATURE_VERIFY=1` 等によりローカル検証可能（`ENV.md`）
- 定時ブログ試験: `GET /api/cron/blog-draft?edition=evening_preview&source=github_actions_cron`（要 `CRON_SECRET` または development で `SKIP_CRON_AUTH=1`）。本番の定時は **GitHub Actions**（**`plan/BLOG_CRON_GHA.md`**）
- 一括: `cd frontend` → `npm run smoke:blog-apis -- --quick` / `npm run smoke:blog-apis`（`frontend/scripts/smoke-blog-apis.mjs`）

---

## ML 3.0 Operational Notes（Round 8, 2026-03-29。2026-07 時点の schema/店舗数は Batch B3 で追記・訂正）

- **モデル方針**: 本番学習（`scripts/train_ml_model.py`）は **店舗別 LightGBM**（`oriental/utils/stores.py` の `ALL_STORE_IDS` = 43店舗 allow-list、`men/women` 回帰モデル）を自動学習。「XGBoost」表記が残っているのは 2026-04-12 の LightGBM 移行前の名残 — 実装ファイル名 `model_xgb.py` は import 互換のため改名していないだけで、中身は LightGBM が優先ロードされる。
- **学習頻度**: **日次（毎日05:30 JST）は固定パラメータで再学習のみ**（Optunaなし、GHA実行時間90%削減）。**週次（毎週月曜07:00 JST）のみ Optuna HPO** を実行。`workflow_dispatch`（手動）時は `vars.ML_OPTUNA_ENABLED` に従う。
- **Optuna HPO**: 店舗ごとに最適なハイパーパラメータを探索（`max_depth`, `learning_rate`, `subsample` 等）。デフォルト 30 trials/店舗。`ML_OPTUNA_ENABLED=1` / `ML_OPTUNA_TRIALS=30` で制御。
- **Early Stopping**: `n_estimators=300` 上限 + `early_stopping_rounds=15` で最適な木の数を自動決定。
- **評価基盤**: 時系列 Train/Test Split（80/20）。Holdout Test で真の汎化精度（MAE/RMSE）を測定。`metadata.json` に永続化。加えて 2026-07〜は本番配信の日次「答え合わせ」（v2 shadow, `forecast-accuracy-track.yml`）が別途 18:10 snapshot / 06:10 score で稼働（詳細 `plan/FORECAST_ACCURACY.md`）。
- **特徴量**: 24 列（`oriental/ml/preprocess.py` の `FEATURE_COLUMNS`）。`same_dow_last_week_total` / `total_slope_30min` / `holiday_block_length` / `holiday_block_position` 等を含む。
- **schema_version**: **v7**（2026-07〜、`oriental/config.py` の既定値・`.env.example`）。列数は v6 と同じ24列で、v7 は `total_slope_30min` のターゲットリーク修正（v6モデルと非互換・再学習必須）。Flask（Render 環境変数）/ GHA（Repository Variable）の `FORECAST_MODEL_SCHEMA_VERSION` を必ず同じ値に揃えること（`plan/DECISIONS.md` 44番、3箇所同期が必要）。
- **時間減衰ウェイト**: 学習時、直近データに高い重み（既定90日半減期の指数減衰。GHA既定は `ML_RECENCY_HALFLIFE_DAYS=45` / `ML_RECENCY_FLOOR=0.25` で直近をより強く重視）。
- **モデルプリロード**: Flask 起動時にバックグラウンドで全店舗モデルをメモリにロード。`DISABLE_MODEL_PRELOAD=1` で無効化可能。
- **重み付け学習**: `sample_weight` で `ML_TRAIN_WEIGHT_PEAK` / `ML_TRAIN_WEIGHT_RAIN`（既定 1.8）を適用。
- **Feature Importance**: `metadata.json` に店舗別で永続化。`/api/forecast_accuracy` で取得可能。
- **Champion/Challenger gate**: `ML_GATE_MAX_REGRESSION_PCT` で退行モデルの本番反映を防ぐ安全ネット（稼働店舗 stale guard も同様）。
- **実験スクリプト配置**: 検証用は `scripts/experiments/` に集約。`scripts/` 直下は本番運用用。

---

## 定期処理・GitHub Actions / ローカル Task Scheduler（旧 CRON.md）

> **2026-07〜、Daily/Weekly Report と CDN warming の「主経路」はオーナーPCのローカル実行に変わった。**
> 下表の GHA 行は Daily/Weekly については **`workflow_dispatch`（緊急時専用）** であり、`schedule:` は
> ワークフローファイル内でコメントアウト済み。ローカル側の正本は `docs/LOCAL_LLM_SETUP.md`。

### ローカル Task Scheduler（オーナーPC・常時起動、主経路）
| 内容 | スケジュール | タスク名 | 実体 |
|------|------|------|------|
| Daily Report（夕方版） | 毎日 18:00 JST | `MEGRIBI-daily-evening` | `scripts/local_report_job.py --edition evening_preview` |
| Daily Report（深夜版） | 毎日 21:30 JST | `MEGRIBI-daily-late` | `scripts/local_report_job.py --edition late_update` |
| Weekly Report | 毎週水曜 06:30 JST | `MEGRIBI-weekly` | `scripts/run_weekly_local.ps1 -Stores all` |
| CDN warming | 19:00〜23:50 JST・10分毎 | `MEGRIBI-warm-cdn` | `scripts/warm_cdn_local.py` |

### GitHub Actions（リポジトリ管理）
| 内容 | スケジュール | Workflow ファイル |
|------|----------------|---------------------|
| Daily Report（**緊急時のみ**、`workflow_dispatch`） | schedule はコメントアウト済み（旧: `0 9`/`30 12` UTC = JST 18:00/21:30） | `trigger-blog-cron.yml` |
| Weekly Report（**緊急時のみ**、`workflow_dispatch`） | schedule はコメントアウト済み（旧: 火 `30 21` UTC = JST 水 06:30） | `generate-weekly-insights.yml` |
| **ML モデル学習・日次**（Optunaなし） | `30 20 * * *` UTC = JST 05:30 | `train-ml-model.yml` |
| **ML モデル学習・週次**（Optuna HPOあり） | `0 22 * * 0` UTC（日曜22:00） = JST 月曜 07:00 | `train-ml-model.yml`（同一ファイル、cron条件分岐） |
| Forecast v2 shadow: snapshot | `10 9 * * *` UTC = JST 18:10 | `forecast-accuracy-track.yml` |
| Forecast v2 shadow: score | `10 21 * * *` UTC = JST 06:10 | `forecast-accuracy-track.yml` |
| Forecast v2 templates 再生成 | `30 22 * * *` UTC = JST 07:30 | `build-templates.yml` |
| CDN warming（**バックアップ**。主はローカル） | `*/10 10-14 * * *` UTC = JST 19:00-23:50・10分毎 | `warm-cdn.yml` |
| **X 自動投稿** | Daily Report 完了後（`workflow_run`）。GHA 経路使用時のみ発火 | `x-auto-post.yml` |
| Public Facts | `30 0` UTC = JST 09:30 | `generate-public-facts.yml` |
| PAT 期限チェック | 月曜 `0 0` UTC = JST 09:00 | `check-pat-expiry.yml` |
| Daily/Weekly 公開監視（ローカル生成の保険） | 各種 | `check-daily-published.yml` / `check-weekly-published.yml` |
| 収集の生存監視 | 各種 | `check-collection-heartbeat.yml` |
| logs バックアップ / 古いログ削除 | 週次 / 手動 | `backup-logs.yml` / `cleanup-old-logs.yml` |
| Blog CI / Python CI | push / PR（schedule なし） | `blog-ci.yml` / `python-ci.yml` |
| E2E テスト | PR + dispatch | `e2e.yml` |
| Blog 再実行（手動） | `workflow_dispatch` のみ | `retry-blog-draft-stores.yml` |
| Blog 手動依頼 | `workflow_dispatch` のみ | `blog-request.yml` |
| 失敗通知（再利用） | `workflow_call` | `notify-on-failure.yml` |

- Weekly（GHA 緊急時経路）: 手動 `workflow_dispatch` で `stores` / threshold 等を指定可能。成果物 `frontend/content/insights/weekly`。matrix はオリエンタル38店舗のみ（相席屋5店舗は対象外）。ローカル主経路（`--stores all`）は全43店舗をカバーする。
- Public Facts: 成果物 `frontend/content/facts/public`

### Actions 失敗通知（任意・2026-03 追加）
- **Secret**: `OPS_NOTIFY_WEBHOOK_URL`（Slack Incoming Webhook の URL 等）。**未設定のときは通知のみスキップ**し、ワークフロー自体は従来どおり。
- **Variable**（任意）: `OPS_NOTIFY_WEBHOOK_TYPE` — `slack`（既定・`{"text":"..."}`）または `discord`（`{"content":"..."}`）。未設定または空なら Slack 形式。
- **呼び出し元**: `generate-weekly-insights.yml` / `trigger-blog-cron.yml`（**全体失敗**・**定時ブログの一部店舗失敗**の両方で `notify-on-failure.yml`）/ `retry-blog-draft-stores.yml` / `generate-public-facts.yml` / `blog-request.yml` が失敗時に再利用ワークフロー `.github/workflows/notify-on-failure.yml` を実行。
- PR 用の `blog-ci.yml` には付けていない（失敗が多く通知が煩いため）。

### 外部 cron（運用側）
- **`/tasks/multi_collect`** を一定間隔で叩く想定。定義は **cron-job.org**（5分毎、`CRON_SECRET` 認証。リポジトリ内に crontab はない）。
- **ブログ下書き（1日2本・JST）**: **通常運用はローカル Ollama**（`docs/LOCAL_LLM_SETUP.md`）。GitHub Actions（`.github/workflows/trigger-blog-cron.yml`）は緊急時の `workflow_dispatch` のみで `GET /api/cron/blog-draft` を叩く。`?edition=evening_preview` / `late_update` と `source=github_actions_cron` を付与。**Secrets** は **`plan/BLOG_CRON_GHA.md`**。
- 追加の定期処理が必要なら `ROADMAP.md` に追記してから仕様化。

### LINE 下書きの `/api/range` limit
- 本番では **`LINE_RANGE_LIMIT`**（未設定時 **500**）。小さすぎるとインサイトが偏る。定時は **`BLOG_CRON_RANGE_LIMIT`**（既定 500）。`plan/ENV.md` / `plan/DECISIONS.md` 12。

### 定時ブログのトラブルシュート

1. **まずローカルジョブを疑う**: 通常運用はローカル Ollama。オーナーPCが起動しているか、Task Scheduler `MEGRIBI-daily-evening`/`-late`/`-weekly` の履歴、`gpu_lock` の競合有無を確認（`docs/LOCAL_LLM_SETUP.md`）。
2. **Supabase `blog_drafts`（最優先）**: 対象日・店舗で **`error_message`** の有無と本文を確認する。ローカルジョブ・Actions のどちらでも、成否の正本はここ。
3. **緊急時に GHA `workflow_dispatch` を使う場合の Secrets**: GitHub → Repository → **Settings → Secrets and variables → Actions** に **`CRON_SECRET`** と **`VERCEL_BLOG_CRON_BASE_URL`**（本番の `https://...vercel.app`、末尾スラッシュなし）があるか。
4. **Actions の実行ログ**: 補助情報。失敗時は `curl` の HTTP ステータス・Vercel 関数ログ（401 なら `CRON_SECRET` 不一致）。
5. **一部店舗だけ失敗したとき（GHA 経路使用時）**: **Actions → Retry blog draft (selected stores)** で `stores` に slug をカンマ区切り指定して再実行（`plan/BLOG_CRON_GHA.md`）。
6. **Vercel の古い Cron**: 過去に Vercel Cron を有効にしていた場合、ダッシュボード **Settings → Cron Jobs** に古いジョブが残っていれば **削除**（コード側は `vercel.json` なし）。

**通常運用の正本**は **`docs/LOCAL_LLM_SETUP.md`**。**緊急時 GHA 手順・Secrets**は **`plan/BLOG_CRON_GHA.md`**。監視の要約・再実行の入口は **`STATUS.md`**（リポジトリ直下）。同期 HTTP の限界を超える場合の将来案は **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。

---

## Production Notes
- Backend: Render (Flask) / Frontend: Vercel (Next.js 16)
- Vercel に `BACKEND_URL` を設定
- LINE 下書き: `plan/ENV.md`。**n8n は使わない。**

---

## Troubleshooting
- `/api/range` が空: Supabase `logs` と `/tasks/multi_collect` を確認
- Forecast 503: `ENABLE_FORECAST=1`
- DNS エラー: URL を安易に変えず、ログで確認
- `/insights/weekly` が読めない: `index.json` の有無・JSON 破損
- **ブラウザで `/api/range` が 502**: Flask（`BACKEND_URL`、通常 `http://127.0.0.1:5000`）が起動していない、または URL が間違い。Flask を起動してから再読み込み。
- **予測が直近値に引きずられる（秘伝のタレ）**: ラグ/MAへの依存が強すぎる可能性。`scripts/experiments/delta_target_nagasaki.py` と `scripts/experiments/ablation_signal_extraction.py` で Delta モデルを再検証し、AUC/Gain を確認してから本番ハイパラ・重みを調整する。

### Next.js `npm run dev`（よくあるエラー）

1. **`cd frontend` で「パスが存在しません」**  
   すでに **`.../riental-lounge-monitor-main/frontend`** にいるときは **`cd frontend` をしない**（二重になる）。正しいカレントは `next.config.ts` と `package.json` がある **`frontend` 直下**。

2. **`Unable to acquire lock` … `is another instance of next dev running?`**  
   **別ターミナルで `next dev` が動いたまま**の可能性が高い。  
   - 不要なターミナルで **Ctrl+C** で停止する。  
   - 止まらない場合は **タスクマネージャー**で `Node.js` を終了。  
   - すべて止めたうえで、まだロックする場合のみ **`frontend/.next/dev/lock` を削除**（dev を起動していないときだけ）。

3. **`Port 3000 is in use` → 3001 で起動**  
   既に 3000 を使っているプロセスがある。上記と同様に **重複した `next dev` を止める**か、表示どおり **`http://localhost:3001`** で開く。

4. **`[baseline-browser-mapping] The data in this module is over two months old`**  
   **警告のみ**で開発は続行可。消したい場合（任意）: `cd frontend` → `npm i baseline-browser-mapping@latest -D`。

---

## HTTP スモーク（VS Code REST Client）
`scripts/dev/smoke-requests.http` を参照。

## ブログ下書きの Git 用エクスポート（Supabase → ローカル）
- `cd frontend` のうえで `npm run drafts:export`（要 `.env.local` の service role）。詳細は `plan/BLOG_PIPELINE.md` §3b。
