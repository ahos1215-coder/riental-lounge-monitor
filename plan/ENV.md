# ENV
Last updated: 2025-12-16 / commit: cf6d7b5

「今必要な env と置き場所」を最小限で整理する（値そのものは書かない）。

## Frontend（Next.js / Vercel）
- 置き場所（ローカル）: `frontend/.env.local`
- 置き場所（本番）: Vercel の Environment Variables
- 使用箇所: Next API routes（`frontend/src/app/api/*/route.ts`）が `process.env.BACKEND_URL` を参照して backend に proxy する。

`frontend/.env.local`（例）
```env
BACKEND_URL=http://localhost:5000
NEXT_PUBLIC_BASE_URL=http://localhost:3000
```

- Vercel に設定するキー名（値は環境ごとに設定）
  - `BACKEND_URL`
  - `NEXT_PUBLIC_BASE_URL`（任意。現状はコード参照が無いが、絶対 URL が必要な場合に備えて保持）

## Backend（Flask / Render）
- 置き場所（ローカル）: リポジトリ直下の `.env`（`oriental/config.py` が読みに行く）
- 置き場所（本番）: Render の Environment Variables

必須（`DATA_BACKEND=supabase` 運用の前提）
- `DATA_BACKEND`（`supabase`）
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`（または互換用に `SUPABASE_SERVICE_KEY`）

よく使う（任意）
- `STORE_ID`（`?store` 未指定時のデフォルト。例: `ol_nagasaki`）
- `MAX_RANGE_LIMIT`（既定 50000）
- `ENABLE_FORECAST`（`1` のときのみ `/api/forecast_*` を有効化）

レガシー/補助（必要なときだけ）
- Google Sheet/GAS: `ENABLE_GAS`, `GAS_URL`/`GAS_WEBHOOK_URL`, `GS_WEBHOOK_URL`, `GS_READ_URL`
- Weather: `ENABLE_WEATHER`, `WEATHER_LAT`, `WEATHER_LON`
- Places（本流ではない）: `GOOGLE_PLACES_API_KEY`（`/tasks/update_second_venues` のみ）

## 絶対にコミットしないもの
- `.env` / `frontend/.env.local`
- `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_SERVICE_KEY`（サービスロール）
- `NEXT_PUBLIC_*` に秘密値（ブラウザへ配布される）
