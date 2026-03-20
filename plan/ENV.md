# ENV
Last updated: 2025-12-23
Target commit: 10e50d6

値そのものは書かず、環境変数名のみ記載。

## Frontend (Next.js / Vercel)
置き場所:
- ローカル: `frontend/.env.local`
- 本番: Vercel Environment Variables

主な変数:
- `BACKEND_URL`（Next API routes が backend を呼ぶための base URL）
- `NEXT_PUBLIC_BASE_URL`（任意。絶対 URL が必要な場面やスクリプトで利用）
- `NEXT_PUBLIC_SHOW_FACTS_DEBUG`（`"1"` のとき Facts の debug notes を表示）

注意:
- `NEXT_PUBLIC_*` はブラウザに配布されるため秘密値を入れない。

## Backend (Flask / Render)
置き場所:
- ローカル: リポジトリ直下 `.env`
- 本番: Render Environment Variables

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
