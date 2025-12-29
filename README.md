# MEGRIBI (riental-lounge-monitor-main)
Last updated: 2025-12-29 / commit: 4299ff1

MEGRIBI は Supabase logs を source of truth とする混雑モニタ + blog/facts 運用のリポジトリです。
バックエンドは Flask、フロントエンドは Next.js 16 (App Router) で構成します。

## Repository Layout
- `app.py`, `wsgi.py`: Flask entrypoint
- `oriental/`: backend (Flask API)
- `frontend/`: Next.js 16 frontend
- `frontend/content/blog/`: blog MDX
- `frontend/content/facts/public/`: public facts JSON + index.json
- `plan/`: SSOT docs (制約・運用・契約)

## Local Development (PowerShell)

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

### Smoke Checks
```powershell
curl.exe "http://127.0.0.1:5000/healthz"
curl.exe "http://127.0.0.1:5000/api/range?store=shibuya&limit=400"
```

## Blog + Public Facts
1) `frontend/content/blog/*.mdx` に記事を追加/更新。
   - 必須: `title`, `date`(YYYY-MM-DD), `store`, `facts_id` または `facts_id_public`
   - 任意: `description`, `categoryId`, `level`, `period`, `draft`
2) Public facts を生成:
```powershell
cd frontend
$env:BACKEND_URL="http://127.0.0.1:5000"
npm run facts:generate
node scripts/build-public-facts-index.mjs
```
3) `frontend/content/facts/public/*.json` と `index.json` を commit/push。

## Draft Preview Gate
- `draft: true` の記事は通常アクセスで非表示。
- `?preview=<token>` が `BLOG_PREVIEW_TOKEN` と一致する場合のみ表示。
- metadata も同じ gate を通す（draft の title/description 漏れ防止）。

## Notes / Constraints
- `/api/range` の公開契約は `store` + `limit` のみ。夜窓(19:00-05:00)の絞り込みはフロント責務。
- Supabase → Flask → Next.js のレイヤ構造を維持（フロントから Supabase 直叩きしない）。
- Supabase Python SDK は不要。backend は REST (`requests`) を使用。
- Secrets は env のみ。`.env` / `frontend/.env.local` は commit しない。
- `.env` は **UTF-8 no BOM** で保存（BOM があると `SUPABASE_URL` が読めない）。

## Legacy (Google Sheets/GAS)
- Google Sheet/GAS 経路は legacy fallback のみ。拡張しない。
