# STATUS
Last updated: 2026-03-24
Target commit: (see git)

## 現在動いている機能

### Backend (Flask / Render)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（**`store` / `limit` のみ**。Supabase は `ts.desc` 取得 → 返却は `ts.asc`、**サーバ側の夜窓フィルタなし**）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
  - **店舗別最適化モデル（ML 2.0）本番稼働中**。全38店舗で固有の重みを使った推論を有効化済み。
  - `model_registry.py` は `metadata.json` の `has_store_models` / `store_models` を検証し、**店舗別モデルを最優先でロード**。不整合時は明示エラー、未対応メタデータ時のみグローバルモデルへフォールバック。
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口 → Supabase `logs`）
- `/tasks/tick` / `/tasks/collect` / `/tasks/seed`（レガシー・ローカル向け）
- `/tasks/update_second_venues`（任意。`GOOGLE_PLACES_API_KEY` がある場合のみ）
- 互換維持のプレースホルダ: `/api/heatmap` `/api/summary` `/api/range_prevweek` `/api/stores/list`

### Frontend (Next.js 16 / Vercel)
- `/`, `/stores`, `/store/[id]`, `/blog`, `/blog/[slug]`, `/insights/weekly`, `/insights/weekly/[store]`, `/mypage`
- **Web UI（2026-03 以降の磨き込み）**: トップ `/` は `stores.ts` ベースの `StoreCard`＋ブログ新着は `getAllPostMetas` の実記事（`home-client.tsx` / サーバー `page.tsx`）。店舗 `/store/[id]` は他店カードの `stats` 省略＋`Suspense` スケルトン＋お気に入りトグル。`/stores` はダミー統計をやめ、リージョン数・エリア例など掲載データに基づく表示。**`/mypage`**: お気に入り・閲覧履歴（`meguribiStorage.ts` / `localStorage`）・主要ページへのショートカット。
- **補足**: 店舗詳細の正規パスは **`/store/[id]`（単数）**。`/stores/[id]`（複数）は意図的に未提供で、404 が正常。
- **店舗プレビュー UI** の夜窓（19:00–05:00）判定: `frontend/src/app/hooks/useStorePreviewData.ts`
- 二次会スポットは map-link 方式（`frontend/src/app/config/secondVenueMapLinks.ts`）
- **LINE Webhook（本番パス）**
  - `POST /api/line`（`frontend/src/app/api/line/route.ts`）: 署名検証 → **レート制限**（グローバル／分＋ユーザーあたり下書き／時、`lineWebhookLimits.ts`）→ テキスト解析 → `BACKEND_URL` 経由で `/api/range` / `/api/forecast_today` → **`insightFromRange.ts`** でインサイト化 → **Gemini** で MDX 下書き → Supabase **`blog_drafts`** 保存 → LINE 返信
  - `GET /api/line`: ヘルス `{"ok":true,"service":"line-webhook"}`
- **OGP / メタデータ**: ルート `metadataBase`（`NEXT_PUBLIC_SITE_URL` 等）、動的 OG 画像 `opengraph-image.tsx`、主要ページの `openGraph` / `twitter`（ブログ記事は canonical 付き）
- **週次 Insights UI**: `/insights/weekly/[store]` に Recharts 可視化（`WeeklyStoreCharts.tsx`）。JSON の **`series_compact`**（`scripts/generate_weekly_insights.py` が出力、最大約240点）で時系列。旧 JSON はプレースホルダ表示。
- **ブログ frontmatter**: Zod 形状検証＋日付形式チェック（`blogFrontmatter.ts` / `content.ts` の `gateBlogFrontmatter`）。`BLOG_STRICT_FRONTMATTER` / `BLOG_LOG_FRONTMATTER` は `plan/ENV.md`。
- その他 Next API routes: `/api/range` 等は Flask へのプロキシ（既存）

### LINE 下書きパイプライン（要点）
- **n8n は使わない（廃止）**。司令塔は Next.js のみ。
- インサイト: `frontend/src/lib/blog/insightFromRange.ts`  
  - まず **今夜窓**（JST 当日 19:00〜翌 05:00）。窓内サンプルが 0 かつ `/api/range` に行がある場合、**同一日の全日（JST 0:00〜23:59）** にフォールバック（日中テストでも数値が出る）。
- 下書き生成: `frontend/src/lib/blog/draftGenerator.ts`（既定 Gemini モデルは **`gemini-2.5-flash`**、404 時は `gemini-2.5-flash-lite` 等。429 はリトライ）
- 意図解析: `frontend/src/lib/line/parseLineIntent.ts`

### Content / Batch
- Weekly Insights: GitHub Actions → `frontend/content/insights/weekly` + `index.json`
- **定時ブログ（本番）**: `.github/workflows/trigger-blog-cron.yml`（全店舗・matrix）。**失敗店舗のみの再実行**は `.github/workflows/retry-blog-draft-stores.yml`。**一部店舗失敗時の Slack/Discord**（`OPS_NOTIFY_WEBHOOK_URL` 設定時）は `trigger-blog-cron.yml` 内の集計ジョブ。成否の正本は Supabase `blog_drafts`（運用要約はリポジトリ直下 **`STATUS.md`**、`plan/BLOG_CRON_GHA.md`）。将来の非同期化メモは **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。
- **GHA 失敗通知**（任意）: `OPS_NOTIFY_WEBHOOK_URL` 設定時、週次 Insights・定時ブログトリガ・Public Facts・Blog Request の失敗で Slack/Discord に POST（`.github/workflows/notify-on-failure.yml`）
- Public Facts: GitHub Actions → `frontend/content/facts/public`
- Facts の debug notes は `NEXT_PUBLIC_SHOW_FACTS_DEBUG=1` のときのみ表示

## 動作確認の最小手順
- Backend: `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- Frontend: `/insights/weekly` が `index.json` を読めること
- **LINE（本番）**: Vercel に LINE / Gemini / Supabase / `BACKEND_URL` が揃い、LINE からテキスト送信 → 返信・`blog_drafts` に行が増えること

## 既知の制限 / 注意
- 週次インサイト生成は `/api/range` の可用性に依存（Actions はタイムアウト/リトライあり）
- `/api/current` はローカル保存の最新値のため、Supabase の最新とは一致しない場合がある（**方針メモ**: `plan/API_CURRENT.md`）
- `/api/range` の **`limit` が小さい**（過去例: 20）と、その日の夜以外のサンプルしか取れずインサイトが偏ることがある。**現行既定は 500**（`LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT`）で、必要時は運用で調整。
- インサイトの **`avoid_time`** は実装上「窓内で total が最小の時刻」（= **混雑が落ち着いている目安**）。「避けるべき時刻」と誤読されないよう、記事文言では提案型の表現を優先（`ROADMAP.md` 参照）。
