# ENV
Last updated: 2025-12-29 / commit: fb524be

環境変数は **値をコミットしない**。`.env` / `frontend/.env.local` は gitignore。

## Frontend (Next.js / Vercel)
- 置き場所 (local): `frontend/.env.local`
- 置き場所 (prod): Vercel Environment Variables

主要キー:
- `BACKEND_URL` (backend API base)
- `BLOG_PREVIEW_TOKEN` (draft preview gate; server-only)
- `NEXT_PUBLIC_SHOW_FACTS_DEBUG` (optional; Facts debug notes)
- `NEXT_PUBLIC_BASE_URL` (optional; 絶対URLが必要な場合のみ)

注意:
- `NEXT_PUBLIC_*` に秘密値を入れない。

## Backend (Flask / Render)
- 置き場所 (local): repo root `.env`（`oriental/config.py` が読み込む）
- 置き場所 (prod): Render Environment Variables

主要キー:
- `DATA_BACKEND` (default: `supabase`)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (fallback: `SUPABASE_SERVICE_KEY`)
- `SUPABASE_STORE_ID` or `STORE_ID` (default store)
- `MAX_RANGE_LIMIT` (default: 50000)

Forecast / window:
- `ENABLE_FORECAST` (1 で有効)
- `FORECAST_FREQ_MIN` (default: 15)
- `NIGHT_START_H`, `NIGHT_END_H` (forecast window)
- `WINDOW_START`, `WINDOW_END` (collection window)

Other:
- `TIMEZONE` (default: Asia/Tokyo)
- `HTTP_TIMEOUT_S`, `HTTP_RETRY`
- `DATA_DIR`, `DATA_FILE`
- Legacy GAS: `GS_WEBHOOK_URL`, `GS_READ_URL`
- Optional Places: `GOOGLE_PLACES_API_KEY`
- `PORT`, `FLASK_DEBUG`

## UTF-8 BOM 注意 (重要)
`.env` が UTF-8 BOM だと `\ufeffSUPABASE_URL` になり読み込めない事故が起きる。
PowerShell で no BOM に書き直す例:
```powershell
$path = ".env"
$raw = Get-Content -Raw $path
[System.IO.File]::WriteAllText($path, $raw, New-Object System.Text.UTF8Encoding($false))
```
