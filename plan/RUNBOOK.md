# RUNBOOK

Operational tasks for MEGRIBI.

## Services
- Backend: Flask (`python app.py`), default `DATA_BACKEND=supabase`.
- Frontend: Next.js 16 (`npm run dev`), consumes backend `/api/*`.
- Cron: `/tasks/tick` every 5 minutes in production; collects 38 stores and updates forecasts when enabled.

## Start / Stop (Local)
```sh
# Backend
set DATA_BACKEND=supabase
python app.py

# Frontend
cd frontend
npm run dev
```
- Visit `http://localhost:3000/?store=nagasaki`.

## Health Checks
- Range: `curl "http://127.0.0.1:5000/api/range?store=nagasaki&limit=400"`; expect newest nights included and `ts` ascending.
- Forecast (when `ENABLE_FORECAST=1`): `curl "http://127.0.0.1:5000/api/forecast_today?store=nagasaki"`.
- Cron status: check server logs for `/tasks/tick` success every 5 minutes.

## Backup ZIP (User-driven)
1) Stop backend/cron if running.
2) From repo root, run (Windows PowerShell):
```powershell
$date = Get-Date -Format "yyyyMMdd_HHmmss"
Compress-Archive -Path oriental,frontend,requirements.txt,app.py -DestinationPath "backup_$date.zip"
```
3) Store ZIP securely. Restart services as needed.

## Incident Playbook
- Missing recent data in UI: call `/api/range?limit=400` to verify newest records exist; if not, check `/tasks/tick` logs and Supabase insert errors.
- Forecast absent: confirm `ENABLE_FORECAST=1` and cron success; frontend will still render actuals.
- Store mismatch: confirm `?store=` query and env default; `?store` overrides env.

## Maintenance
- Do not reintroduce `from/to` filtering on the backend; night filtering is frontend-only.
- If Supabase is unavailable, legacy path may respond but is not a priority to fix beyond parity.

## 二次会スポット (frontend) 確認
- `.env` に `GOOGLE_PLACES_API_KEY` をセットした上で `npm install` → `npm run dev` を起動。
- ブラウザで `http://127.0.0.1:3000/?store=nagasaki` を開き、ダッシュボード下部の「Nearby second venues」カードにスポットが並ぶことを確認。
- 距離・ジャンル・営業中バッジ・マップリンクが表示されることを目視チェック。バックエンドが空なら「近隣スポットが見つかりませんでした。」表示になる。
