# STATUS
Last updated: 2025-12-23
Target commit: 10e50d6

## 現在動いている機能
### Backend (Flask)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（`store`/`limit` のみ。Supabase は `ts.desc` → 返却は `ts.asc`、夜窓フィルタなし）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口）
- `/tasks/tick` / `/tasks/collect` / `/tasks/seed`（レガシー・ローカル向け）
- `/tasks/update_second_venues`（任意。`GOOGLE_PLACES_API_KEY` がある場合のみ）
- 互換維持のプレースホルダ: `/api/heatmap` `/api/summary` `/api/range_prevweek` `/api/stores/list`

### Frontend (Next.js 16 / App Router)
- `/`, `/stores`, `/store/[id]`, `/blog`, `/blog/[slug]`, `/insights/weekly`, `/insights/weekly/[store]`, `/mypage`
- `/stores/<id>` は存在しない（404 が正常）
- 夜窓（19:00–05:00）の判定は `frontend/src/app/hooks/useStorePreviewData.ts`
- 二次会スポットは map-link 方式（`frontend/src/app/config/secondVenueMapLinks.ts`）

### Content / Batch
- Weekly Insights: GitHub Actions で生成し `frontend/content/insights/weekly` をコミット、`index.json` を更新
- Public Facts: GitHub Actions で生成し `frontend/content/facts/public` を更新
- Facts の debug notes は `NEXT_PUBLIC_SHOW_FACTS_DEBUG=1` のときのみ表示

## 動作確認の最小手順
- `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- `/insights/weekly` が `index.json` を読めること
- `/insights/weekly/[store]` が `latest_file` を読めること

## 既知の制限/注意
- 週次インサイト生成は `/api/range` の可用性に依存（Actions はタイムアウト/リトライあり）
- `/api/current` はローカル保存の最新値のため、Supabase の最新とは一致しない場合がある
