# RUNBOOK
Last updated: YYYY-MM-DD / commit: TODO

Operational tasks for MEGRIBI (Render backend / Vercel frontend).

## Services
- Backend: Flask (Render Starter, 24h), default `DATA_BACKEND=supabase`.
- Frontend: Next.js 16 (Vercel), calls backend `/api/*`.
- Cron: `/tasks/tick` every 5 minutes in production; collects ~38 stores and updates forecasts when `ENABLE_FORECAST=1`.

## Frontend Development

### ローカル起動
```
cd frontend
npm install
npm run dev
```

### 本番デプロイ（Vercel）
- main ブランチへ push → Vercel が自動デプロイ。
- Next.js 16 ビルドルール:
  - `useSearchParams` を使うコンポーネントは `Suspense` 配下に置く。
  - Recharts の `TooltipProps` は `label`/`payload` を独自型で拡張して型エラーを防ぐ。
- ドメイン: `https://meguribi.jp`（反映確認は Shift+F5 または DevTools Network→Disable Cache）。

## Backend Operations (Render)
- `DATA_BACKEND=supabase` をデフォルト設定。
- `/tasks/tick` が 5 分間隔で動作しているか Render ログで確認。
- `/api/range?store=nagasaki&limit=400` が `ts.asc` で最新を返すか確認。サーバ側で時間フィルタを入れない。

## Start / Stop (Local)
```
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
- Forecast (when `ENABLE_FORECAST=1`): `curl "http://127.0.0.1:5000/api/forecast_today?store=nagasaki"` (empty array is acceptable when disabled).
- Cron status: check Render logs for `/tasks/tick` success every 5 minutes.

## Incident Playbook
- Missing recent data: hit `/api/range?limit=400`; if empty, check `/tasks/tick` logs and Supabase insert path.
- Forecast absent: ensure `ENABLE_FORECAST=1`; frontend should still render actuals.
- Store mismatch: confirm `?store=` query; env default otherwise.
- DNS キャッシュ疑い: Shift+F5 または DevTools Network→Disable Cache。DNSやENOTFOUND系はコードを書き換えず、まず本番/別環境での再現確認を提案。

## Second Venues (map-link)
- 現行仕様は frontend の Google マップ検索リンクのみ。バックエンドや Google Places API は使用しない。
- UI で「Nearby second venues」のボタンが Google Maps 検索を開くことを確認。

## Backup ZIP (User-driven)
1) Stop backend/cron if running.
2) From repo root (Windows PowerShell):
```
$date = Get-Date -Format "yyyyMMdd_HHmmss"
Compress-Archive -Path oriental,frontend,requirements.txt,app.py -DestinationPath "backup_$date.zip"
```
3) Store ZIP securely. Restart services as needed.

## Maintenance
- Do not reintroduce `from/to` filtering on the backend; night filtering is frontend-only.
- If Supabase is unavailable, legacy path may respond but is not a priority beyond parity.
