# RUNBOOK
Last updated: 2025-12-29 / commit: cf8c998

Operational tasks for MEGRIBI (Render backend / Vercel frontend).

## Local Setup (PowerShell)

### Backend (Flask)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DATA_BACKEND="supabase"
$env:SUPABASE_URL="<YOUR_SUPABASE_URL>"
$env:SUPABASE_SERVICE_ROLE_KEY="<YOUR_SERVICE_ROLE_KEY>"

python app.py
```

### Frontend (Next.js 16)
```powershell
cd frontend
npm install
$env:BACKEND_URL="http://127.0.0.1:5000"
npm run dev
```

### Build
```powershell
cd frontend
npm run build
```

## API Smoke Checks
PowerShell では `&` を含む URL を必ず引用符で囲む（`curl.exe` を使う）。
```powershell
curl.exe "http://127.0.0.1:5000/healthz"
curl.exe "http://127.0.0.1:5000/api/range?store=shibuya&limit=400"
curl.exe "http://127.0.0.1:5000/api/forecast_today?store=shibuya"
```

## Blog Draft / Preview
- `draft: true` の記事は通常アクセスで 404。
- `?preview=<token>` が `BLOG_PREVIEW_TOKEN` と一致すると表示。
- metadata も同じ gate を通す。

## Public Facts Generation
```powershell
cd frontend
$env:BACKEND_URL="http://127.0.0.1:5000"
npm run facts:generate
node scripts/build-public-facts-index.mjs
```
- 生成物: `frontend/content/facts/public/*.json` と `index.json`
- 生成元: backend `/api/range` → 足りない場合は `/api/forecast_today`

## .env UTF-8 BOM Issue (重要)
`.env` に BOM があると `\ufeffSUPABASE_URL` になり読み込めない事故が起きる。
PowerShell で no BOM に書き直す例:
```powershell
$path = ".env"
$raw = Get-Content -Raw $path
[System.IO.File]::WriteAllText($path, $raw, New-Object System.Text.UTF8Encoding($false))
```

## PowerShell Notes
`python - << 'PY'` は使えない。here-string を `python -` に渡す:
```powershell
@'
print("hello")
'@ | python -
```

## Backup ZIP (User-driven)
Desktop が OneDrive にリダイレクトされる場合があるため `DesktopDirectory` を使う。
```powershell
$desktop = [Environment]::GetFolderPath("DesktopDirectory")
$date = Get-Date -Format "yyyyMMdd_HHmmss"
Compress-Archive -Path oriental,frontend,requirements.txt,app.py -DestinationPath (Join-Path $desktop "backup_$date.zip")
```

## TODO
- LINE/n8n は次スレで整理・実装する。
