# STATUS
Last updated: 2026-03-21
Target commit: (see git)

## 現在動いている機能

### Backend (Flask / Render)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（**`store` / `limit` のみ**。Supabase は `ts.desc` 取得 → 返却は `ts.asc`、**サーバ側の夜窓フィルタなし**）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口 → Supabase `logs`）
- `/tasks/tick` / `/tasks/collect` / `/tasks/seed`（レガシー・ローカル向け）
- `/tasks/update_second_venues`（任意。`GOOGLE_PLACES_API_KEY` がある場合のみ）
- 互換維持のプレースホルダ: `/api/heatmap` `/api/summary` `/api/range_prevweek` `/api/stores/list`

### Frontend (Next.js 16 / Vercel)
- `/`, `/stores`, `/store/[id]`, `/blog`, `/blog/[slug]`, `/insights/weekly`, `/insights/weekly/[store]`, `/mypage`
- `/stores/<id>` は存在しない（404 が正常）
- **店舗プレビュー UI** の夜窓（19:00–05:00）判定: `frontend/src/app/hooks/useStorePreviewData.ts`
- 二次会スポットは map-link 方式（`frontend/src/app/config/secondVenueMapLinks.ts`）
- **LINE Webhook（本番パス）**
  - `POST /api/line`（`frontend/src/app/api/line/route.ts`）: 署名検証 → テキスト解析 → `BACKEND_URL` 経由で `/api/range` / `/api/forecast_today` → **`insightFromRange.ts`** でインサイト化 → **Gemini** で MDX 下書き → Supabase **`blog_drafts`** 保存 → LINE 返信
  - `GET /api/line`: ヘルス `{"ok":true,"service":"line-webhook"}`
- その他 Next API routes: `/api/range` 等は Flask へのプロキシ（既存）

### LINE 下書きパイプライン（要点）
- **n8n は使わない（廃止）**。司令塔は Next.js のみ。
- インサイト: `frontend/src/lib/blog/insightFromRange.ts`  
  - まず **今夜窓**（JST 当日 19:00〜翌 05:00）。窓内サンプルが 0 かつ `/api/range` に行がある場合、**同一日の全日（JST 0:00〜23:59）** にフォールバック（日中テストでも数値が出る）。
- 下書き生成: `frontend/src/lib/blog/draftGenerator.ts`（既定 Gemini モデルは **`gemini-2.5-flash`**、404 時は `gemini-2.5-flash-lite` 等。429 はリトライ）
- 意図解析: `frontend/src/lib/line/parseLineIntent.ts`

### Content / Batch
- Weekly Insights: GitHub Actions → `frontend/content/insights/weekly` + `index.json`
- Public Facts: GitHub Actions → `frontend/content/facts/public`
- Facts の debug notes は `NEXT_PUBLIC_SHOW_FACTS_DEBUG=1` のときのみ表示

## 動作確認の最小手順
- Backend: `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- Frontend: `/insights/weekly` が `index.json` を読めること
- **LINE（本番）**: Vercel に LINE / Gemini / Supabase / `BACKEND_URL` が揃い、LINE からテキスト送信 → 返信・`blog_drafts` に行が増えること

## 既知の制限 / 注意
- 週次インサイト生成は `/api/range` の可用性に依存（Actions はタイムアウト/リトライあり）
- `/api/current` はローカル保存の最新値のため、Supabase の最新とは一致しない場合がある
- `/api/range` の **`limit` が小さい**（例: 20）と、その日の夜以外のサンプルしか取れずインサイトが偏ることがある → `frontend/src/app/api/line/route.ts` の `RANGE_LIMIT` で調整可能
- インサイトの **`avoid_time`** は実装上「窓内で total が最小の時刻」（＝空きやすいサンプル）。日本語の「避けたい」表現とズレる場合は記事ルール側で補足予定（`ROADMAP.md` 参照）
