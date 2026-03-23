# ENV
Last updated: 2026-03-23
Target commit: (see git)

値そのものは書かず、環境変数名のみ記載。

## Frontend (Next.js / Vercel)
置き場所:
- ローカル（推奨）: **リポジトリルート**の `.env.local`（`frontend/next.config.ts` の `loadEnvConfig(..)` で親ディレクトリから読み込み）
- ローカル（代替）: `frontend/.env.local`（Next の標準読み込み。ルートと併用する場合は重複キーに注意）
- 本番: Vercel Environment Variables

主な変数:
- `BACKEND_URL`（Next API routes が backend を呼ぶための base URL）
- `NEXT_PUBLIC_BASE_URL`（任意。絶対 URL が必要な場面やスクリプトで利用）
- `NEXT_PUBLIC_SITE_URL`（任意。**OGP・canonical の正本**に使う推奨。末尾スラッシュなし。未設定時は `NEXT_PUBLIC_BASE_URL` → Vercel の `VERCEL_URL` → `localhost`）
- `NEXT_PUBLIC_SHOW_FACTS_DEBUG`（`"1"` のとき Facts の debug notes を表示）

ブログ MDX frontmatter（`frontend/src/lib/blog/blogFrontmatter.ts` / `content.ts`）:
- `BLOG_STRICT_FRONTMATTER`（`"1"` のとき Zod 形状検証または date 形式警告で **`next build` を失敗**させる。CI 用）
- `BLOG_LOG_FRONTMATTER`（`"1"` のとき本番でも frontmatter 警告を **console に出す**）

LINE Webhook（`frontend/src/app/api/line/route.ts`）:
- `LINE_RANGE_LIMIT`（任意。`/api/range` の `limit`。**未設定時は 500**（定時の `BLOG_CRON_RANGE_LIMIT` 既定と整合）。旧 20 は偏りやすい）
- **レート制限**（`frontend/src/lib/rateLimit/lineWebhookLimits.ts`）: Webhook は LINE サーバー経由のため **IP ではなく**（1）署名成功後の **全体スループット**（2）**ユーザー ID あたりの下書きパイプライン**を制限する。
  - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`（**本番必須推奨**。Upstash Redis。未設定時はプロセス内メモリのみでサーバレスでは揮発しやすく、実運用のレート制限は弱い）
  - `LINE_WEBHOOK_GLOBAL_PER_MINUTE`（任意。全体上限／分。**既定 200**）
  - `LINE_WEBHOOK_DRAFT_PER_USER_HOUR`（任意。同一 LINE ユーザーあたり下書き生成／時。**既定 20**）
  - `LINE_RATE_LIMIT_DISABLED`（`"1"` のとき制限オフ。ローカル検証のみ推奨）
- `LINE_CHANNEL_SECRET`（`x-line-signature` 検証。本番では必須）
- `LINE_CHANNEL_ACCESS_TOKEN`（返信メッセージ用）
- `SKIP_LINE_SIGNATURE_VERIFY`（`"1"` のとき署名検証をスキップ。ローカル検証用のみ）
- `GEMINI_API_KEY`（下書き生成）
- `GEMINI_MODEL`（任意。既定 `gemini-2.5-flash`。404 時は `gemini-2.5-flash-lite` を試行。古い `gemini-1.x` / `gemini-2.0-flash` 等はコード側で `gemini-2.5-flash` に正規化）
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`（`blog_drafts` への INSERT。未設定時は生成のみ・DB 保存なし）

定時ブログ（GitHub Actions から `GET` → `frontend/src/app/api/cron/blog-draft/route.ts`）:
- `CRON_SECRET`（**Vercel の Environment Variables** に設定し、GHA の Repository Secret と**同じ値**にする。`Authorization: Bearer` で検証）
- `BLOG_CRON_STORE_SLUG` または `BLOG_CRON_STORE_SLUGS`（カンマ区切り。未設定時は `DEFAULT_STORE`＝先頭店舗）
- `BLOG_CRON_RANGE_LIMIT`（任意。`/api/range` の limit。未設定時は 500）
- `BLOG_BACKEND_FETCH_TIMEOUT_MS`（任意。Next から Flask への `fetch` の打ち切り。**未設定時は 40000**（40秒）。夜間データが多い店舗で `api_range_error:This operation was aborted` が出る場合に増やす。5000〜120000 の範囲）
- `SKIP_CRON_AUTH`（**ローカル development のみ** `"1"` で認証スキップ。本番では使わない）

注意:
- `NEXT_PUBLIC_*` はブラウザに配布されるため秘密値を入れない。

### GitHub Actions（Repository — Vercel ではない）
- `OPS_NOTIFY_WEBHOOK_URL`（任意。**Secret**。週次 Insights・定時ブログ・Public Facts・Blog Request の失敗時に Webhook POST。未設定なら通知ジョブのみスキップ）
- `OPS_NOTIFY_WEBHOOK_TYPE`（任意。**Variables** 推奨。`slack` または `discord`。未設定・空なら Slack 形式 `{"text":"..."}`）
- `SUPABASE_URL`（**Secret**。`train-ml-model.yml` 用）
- `SUPABASE_SERVICE_ROLE_KEY`（**Secret**。`train-ml-model.yml` 用）
- `FORECAST_MODEL_BUCKET`（**Variables** 推奨。学習済みモデルの Storage バケット）
- `FORECAST_MODEL_PREFIX`（**Variables** 推奨。`forecast/latest` など）
- `FORECAST_MODEL_SCHEMA_VERSION`（**Variables** 推奨。`metadata.json` と推論側の一致チェック用）

### ローカル CLI: `npm run drafts:export`（`frontend/scripts/export-blog-draft.mjs`）
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`（**service role**。`blog_drafts` を REST で読む）
- 読み込み元: リポジトリルートの `.env.local`（`generate-public-facts.mjs` と同様）

## Backend (Flask / Render)
置き場所:
- ローカル: リポジトリ直下 `.env`（任意）および **`.env.local`**（`oriental/config.py` が先に `.env`、続けて `.env.local` を読み込み。Next と同じファイルに `SUPABASE_*` を置ける）
- 本番: Render Environment Variables

注意:
- `SUPABASE_URL` は **`https://xxxx.supabase.co`** 形式（`//` や `https` 抜けは無効）

必須に近いもの（Supabase 運用時）:
- `DATA_BACKEND`（通常 `supabase`）
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`
- `STORE_ID`（または `SUPABASE_STORE_ID`）
- `MAX_RANGE_LIMIT`
- `TIMEZONE`

基本設定:
- `TARGET_URL`
- `STORE_NAME`
- `WINDOW_START` / `WINDOW_END`（レガシー `/tasks/tick` の窓）
- `LOG_LEVEL`
- `HTTP_TIMEOUT_S`
- `HTTP_RETRY`
- `HTTP_USER_AGENT`
- `DATA_DIR`
- `DATA_FILE`
- `PORT`
- `FLASK_DEBUG`

Forecast:
- `ENABLE_FORECAST`
- `FORECAST_FREQ_MIN`
- `NIGHT_START_H` / `NIGHT_END_H`
- `FORECAST_MODEL_BUCKET`（Supabase Storage のモデル配置バケット名。例: `ml-models`）
- `FORECAST_MODEL_PREFIX`（バケット内のモデル配置 prefix。例: `forecast/latest`）
- `FORECAST_MODEL_SCHEMA_VERSION`（`metadata.json` の `schema_version` と一致必須。不一致時は 503）
- `FORECAST_MODEL_REFRESH_SEC`（モデル再取得の TTL 秒。既定 900）
- `FORECAST_MODEL_CACHE_DIR`（Render ローカルキャッシュ先。既定 `data/ml_models`）

推奨モデル配置（`FORECAST_MODEL_PREFIX` 配下）:
- `metadata.json`（`schema_version`, `feature_columns`, `model_men`, `model_women` を含む）
- `model_men.json`（XGBoost Native）
- `model_women.json`（XGBoost Native）

Legacy / Optional:
- `GS_WEBHOOK_URL`
- `GS_READ_URL`
- `GOOGLE_PLACES_API_KEY`（`/tasks/update_second_venues` 用）

## Collector (multi_collect.py)
- `GAS_URL` or `GAS_WEBHOOK_URL`
- `ENABLE_GAS`
- `GAS_MAX_RETRY`
- `BETWEEN_STORES_SEC`
- `ENABLE_WEATHER`
- `WEATHER_LAT` / `WEATHER_LON`
- **Open-Meteo（429 対策）**: `WEATHER_CACHE_TTL_SEC`（既定 **3600**）、`WEATHER_HTTP_MIN_INTERVAL_SEC`（既定 **0.85**）、`WEATHER_HTTP_MAX_RETRIES`（接続エラー等の再試行回数・既定 **3**）、`WEATHER_429_EXTRA_TRIES`（429 時の追加リトライ回数・既定 **1**、**短い sleep のみ**）、`WEATHER_429_RETRY_SLEEP_SEC`（既定 **2.5**）、`WEATHER_CACHE_PATH`（省略時 `.cache/open_meteo_weather_cache.json`）
- **Gunicorn（Render）**: `Procfile` で `--timeout 300`。長い `tasks/multi_collect` の HTTP リクエストが worker timeout で落ちないようにする
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`

## Weekly Insights (scripts/generate_weekly_insights.py)
- `MEGRIBI_BASE_URL`（優先）
- `NEXT_PUBLIC_BASE_URL`（fallback）
- `INSIGHTS_STORES`
- `INSIGHTS_THRESHOLD`
- `INSIGHTS_MIN_DURATION_MINUTES`
- `INSIGHTS_IDEAL`
- `INSIGHTS_GENDER_WEIGHT`
- `INSIGHTS_HTTP_TIMEOUT_SECONDS`
- `INSIGHTS_HTTP_RETRIES`

## Public Facts (frontend/scripts/generate-public-facts.mjs)
- `BACKEND_URL`（または CLI `--backend`）
