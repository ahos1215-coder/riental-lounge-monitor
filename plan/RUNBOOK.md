# RUNBOOK
Last updated: 2025-12-23
Target commit: 10e50d6

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
# frontend/.env.local に必要な環境変数を設定（plan/ENV.md 参照）
npm run dev
```

## Local Checks
- `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- `/api/forecast_today?store=...`（`ENABLE_FORECAST=1` のとき）
- `/insights/weekly` が `index.json` を読めること

## GitHub Actions (Ops)
### Weekly Insights
- Workflow: `Generate Weekly Insights`
- Schedule: `30 15 * * 0` (UTC) = JST 月曜 00:30
- 手動実行: `workflow_dispatch` の inputs で `stores/threshold/min_duration_minutes` を指定可能
- 成果物: `frontend/content/insights/weekly`

### Public Facts
- Workflow: `Generate Public Facts`
- Schedule: `30 0 * * *` (UTC) = JST 09:30
- 成果物: `frontend/content/facts/public`

### Blog CI
- Workflow: `blog-ci`（push / PR の frontend 変更で実行）

## Production Notes
- Backend: Render (Flask)
- Frontend: Vercel (Next.js 16)
- Vercel には `BACKEND_URL` を設定して backend を指す

## Troubleshooting
- `/api/range` が空: Supabase `logs` の状態と `/tasks/multi_collect` の実行を確認
- Forecast が 503: `ENABLE_FORECAST=1` を設定
- DNS / name resolution エラー: URL を書き換えず、別環境で再現確認（Render Logs など）
- `/insights/weekly` が読めない: `index.json` の有無と JSON 破損を確認
