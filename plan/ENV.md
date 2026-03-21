# ENV
Last updated: 2026-03-21
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
- `NEXT_PUBLIC_SHOW_FACTS_DEBUG`（`"1"` のとき Facts の debug notes を表示）

LINE Webhook（`frontend/src/app/api/line/route.ts`）:
- `LINE_CHANNEL_SECRET`（`x-line-signature` 検証。本番では必須）
- `LINE_CHANNEL_ACCESS_TOKEN`（返信メッセージ用）
- `SKIP_LINE_SIGNATURE_VERIFY`（`"1"` のとき署名検証をスキップ。ローカル検証用のみ）
- `GEMINI_API_KEY`（下書き生成）
- `GEMINI_MODEL`（任意。既定 `gemini-2.0-flash`。古い `gemini-1.0-pro` / `gemini-1.5-flash` 等はコード側で `gemini-2.0-flash` に正規化）
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SERVICE_KEY`（`blog_drafts` への INSERT。未設定時は生成のみ・DB 保存なし）

注意:
- `NEXT_PUBLIC_*` はブラウザに配布されるため秘密値を入れない。

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
