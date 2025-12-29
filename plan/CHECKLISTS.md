# CHECKLISTS
Last updated: 2025-12-29 / commit: 4299ff1

## デプロイ前 (Render backend / Vercel frontend)
- [ ] Backend 環境変数: `DATA_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MAX_RANGE_LIMIT=50000`.
- [ ] `ENABLE_FORECAST=1` を設定（無効時は `/api/forecast_*` が 503 を返す）。
- [ ] `/api/range?store=...&limit=400` が `ts.asc` で返る（サーバ側時間フィルタなし）。
- [ ] Frontend build が通る (`npm run build`)。
- [ ] `useSearchParams` は `Suspense` 配下。
- [ ] Recharts Tooltip: `TooltipProps` を拡張して `label`/`payload` を許容。
- [ ] Second venues は map-link UI が表示される。
- [ ] Secrets は env のみ。`NEXT_PUBLIC_*` に秘密値を入れない。

## 欠損データの確認
- [ ] `/api/range?store=...&limit=400` を確認。
- [ ] `/tasks/multi_collect` の実行ログを確認（スケジューラ設定含む）。
- [ ] store ID が一致しているか確認（`store` or `store_id`）。

## Forecast の確認
- [ ] `ENABLE_FORECAST=1` と最近の収集があるか確認。
- [ ] 無効時は `503 { ok:false, error:"forecast-disabled" }` を想定。

## Frontend (Next.js 16)
- [ ] Night window (19:00-05:00) はクライアント側で絞り込む。
- [ ] Second venues map-link ボタンが Google Maps を開く。
- [ ] DNS キャッシュ注意: 反映確認は Shift+F5 または DevTools Network → Disable Cache。

## Backup
- [ ] RUNBOOK の手順で ZIP を作成。
- [ ] ZIP はローカル保管のみ（`.gitignore` で除外）。
