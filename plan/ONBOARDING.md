# ONBOARDING
Last updated: 2025-12-29 / commit: fb524be

「今の MEGRIBI を最初から動かす」ための手順と前提のまとめ。

## 1) Backend (Render / Flask)
- Render で常時起動。`DATA_BACKEND=supabase` をデフォルトに設定。
- 環境変数（例）:
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
  - `STORE_ID` or `SUPABASE_STORE_ID`
  - `MAX_RANGE_LIMIT=50000`
  - `ENABLE_FORECAST` (任意)
- 収集の主経路は `/tasks/multi_collect`。`/tasks/tick` は legacy。
- `.env` は UTF-8 no BOM で保存（BOM 付きだと `SUPABASE_URL` が読めない）。

## 2) Frontend (Vercel / Next.js 16)
- GitHub 連携 → main への push で自動デプロイ。
- `BACKEND_URL` を Render の API に向ける。フロントから Supabase へ直アクセスしない。
- `useSearchParams` を使うコンポーネントは必ず `Suspense` 配下に置く。

## 3) Local Development
```powershell
# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_BACKEND="supabase"
$env:SUPABASE_URL="<YOUR_SUPABASE_URL>"
$env:SUPABASE_SERVICE_ROLE_KEY="<YOUR_SERVICE_ROLE_KEY>"
python app.py

# Frontend
cd frontend
npm install
$env:BACKEND_URL="http://127.0.0.1:5000"
npm run dev
```

## 4) Night Window Responsibility
- 夜窓(19:00-05:00)の判定・絞り込みはフロント専任。
- バックエンドに同等の時間フィルタを入れない。

## 5) Second Venues
- 現行仕様は **map-link frontend only**（Google Maps 検索リンクを生成するだけ）。
- Backend `/api/second_venues` は互換/将来用として残置。

## 6) Supabase
- `logs`/`stores` が single source of truth。
- API キーは env で管理し、ハードコードしない。
