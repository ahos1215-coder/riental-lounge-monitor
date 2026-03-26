# STATUS
Last updated: 2026-03-26
Target commit: (see git)

## 現在動いている機能

### Backend (Flask / Render)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（**`store` / `limit` のみ**。Supabase は `ts.desc` 取得 → 返却は `ts.asc`、**サーバ側の夜窓フィルタなし**）
- `/api/range_multi`（**`stores=slug1,slug2,...` + `limit` 等**。Supabase のみ。店舗一覧の一括 range 取得用）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
  - **店舗別最適化モデル（ML 2.0）本番稼働中**。全38店舗で固有の重みを使った推論を有効化済み。
  - `model_registry.py` は `metadata.json` の `has_store_models` / `store_models` を検証し、**店舗別モデルを最優先でロード**。不整合時は明示エラー、未対応メタデータ時のみグローバルモデルへフォールバック。
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口 → Supabase `logs`）
- `/tasks/tick` / `/tasks/collect` / `/tasks/seed`（レガシー・ローカル向け）
- `/tasks/update_second_venues`（任意。`GOOGLE_PLACES_API_KEY` がある場合のみ）
- `/api/megribi_score`（全店舗 or 指定店舗の megribi_score を返す。`?store=` / `?stores=` 対応。Supabase backend 必須）
- 全 `/tasks/*` エンドポイントに `CRON_SECRET` 認証追加済み
- 旧プレースホルダ API（`/api/heatmap` 等）は削除済み

### Frontend (Next.js / Vercel)

#### ページルート（実装済み）
| パス | 概要 |
|------|------|
| `/` | トップ。「今夜のおすすめ」（megribi_score TOP 5）+ Last visited + ブログ新着 + レポートリンク |
| `/stores` | 全店舗一覧（12件/ページ・地域タブ・`/api/range_multi` バッチ取得） |
| `/store/[id]` | 店舗詳細（単数 `id`。`/stores/[id]` は意図的に404）+ AI レポート要約 + レポート一覧導線 |
| `/reports/daily` | **Daily Report 一覧**（全店舗の最新 Daily Report をカード表示） |
| `/reports/daily/[store_slug]` | **Daily Report 個別**：最新 `content_type='daily'`・`is_published=true` |
| `/reports/weekly` | **Weekly Report 一覧**（全店舗の最新 Weekly Report をカード表示） |
| `/reports/weekly/[store_slug]` | **Weekly Report 個別**：最新 `content_type='weekly'`・`is_published=true` |
| `/blog` | 編集ブログ一覧。Daily/Weekly Report 一覧への誘導バナー付き |
| `/blog/[slug]` | **editorial（`content_type='editorial'`, `is_published=true`）のみ**表示 |
| `/insights/weekly` | Weekly Insights インデックス（`index.json` から）|
| `/insights/weekly/[store]` | Weekly Insights 店舗別（`WeeklyStoreCharts.tsx`、`series_compact` 可視化）|
| `/mypage` | お気に入り・閲覧履歴（`meguribiStorage.ts` / `localStorage`）|

- **LINE Webhook（本番パス）**
  - `POST /api/line`（`frontend/src/app/api/line/route.ts`）: 署名検証 → **レート制限**（グローバル／分＋ユーザーあたり下書き／時）→ テキスト解析（`parseLineIntent.ts`）→ 3 インテント処理：
    - **`draft` / `editorial_analysis`**: `BACKEND_URL` 経由で `/api/range` + `/api/forecast_today` → `insightFromRange.ts` → Gemini MDX → Supabase `blog_drafts`（`content_type='editorial'`, `is_published=false`）→ LINE 返信（「承認してから公開」案内付き）
    - **`approve`**: 最新の未公開 `editorial` 下書きを特定 → `is_published=true` に更新 → `/blog/[public_slug]` の URL を返信
  - `GET /api/line`: ヘルス `{"ok":true,"service":"line-webhook"}`
- **OGP / メタデータ**: ルート `metadataBase`（`NEXT_PUBLIC_SITE_URL` 等）、動的 OG 画像、主要ページの `openGraph` / `twitter`
- **Sitemap**: `/reports/daily`（一覧）＋ `/reports/weekly`（一覧）＋ `/reports/daily/[store_slug]`（priority 0.85 / daily）＋ `/reports/weekly/[store_slug]`（priority 0.8 / weekly）が全店舗分登録済み。旧 `/blog/auto-*` URLは廃止。
- **週次 Insights UI**: `/insights/weekly/[store]` に Recharts 可視化（`WeeklyStoreCharts.tsx`）。`series_compact` で時系列。旧 JSON はプレースホルダ表示。
- **ブログ frontmatter**: Zod 形状検証＋日付形式チェック（`blogFrontmatter.ts` / `content.ts`）。`BLOG_STRICT_FRONTMATTER` / `BLOG_LOG_FRONTMATTER` は `plan/ENV.md`。
- **`/stores`**: 12 店舗/ページ・地域タブ・`/api/range_multi` バッチ取得。予測 API が 503 のときはカードに「予測なし」表示。

### Supabase `blog_drafts` スキーマ（2026-03-26 以降）

| カラム | 型 | 説明 |
|--------|----|------|
| `id` | uuid | PK |
| `facts_id` | text | 一意ID（`UNIQUE` 制約あり） |
| `store_slug` | text | 店舗スラグ |
| `target_date` | text | 対象日 |
| `mdx_content` | text | 生成した MDX 本文 |
| `source` | text | 生成元（`github_actions_cron` / `line_webhook` 等） |
| `content_type` | text | `'daily'` / `'weekly'` / `'editorial'` |
| `is_published` | boolean | `true` = 公開済み（daily/weekly は生成時 true、editorial は LINE 承認後 true）|
| `edition` | text | `evening_preview` / `late_update` / `weekly` / null |
| `public_slug` | text | `/blog/[slug]` の公開パス（`UNIQUE where not null`）|
| `created_at` | timestamp | |
| `updated_at` | timestamp | |
| インデックス | — | `facts_id` UNIQUE、`public_slug` UNIQUE (where not null)、`(content_type, is_published, store_slug, created_at)` |

Migration: `supabase/migrations/20260326000000_blog_drafts_content_split.sql`

### Content / Batch

#### Daily Report（`content_type='daily'`, `is_published=true`）
- **Workflow**: `.github/workflows/trigger-blog-cron.yml`（`workflow_dispatch` 専用・スケジュールなし）
- **トリガー**: **cron-job.org** が JST 18:00 / 21:30 に GitHub `workflow_dispatch` API を呼び出す（GHA 内部 schedule は削除済み）
- **構成**: 38店舗 × 独立 matrix ジョブ、`max-parallel: 15`、`continue-on-error: true`
- **エンドポイント**: `GET /api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
- **保存**: Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`）
- 失敗店舗のみ再実行: `retry-blog-draft-stores.yml`
- 部分失敗通知: `summarize-blog-matrix` → `notify-partial-blog-failures`（`OPS_NOTIFY_WEBHOOK_URL` 設定時）

#### Weekly Report（`content_type='weekly'`, `is_published=true`）
- **Workflow**: `.github/workflows/generate-weekly-insights.yml`（毎週水曜 06:30 JST = UTC 火曜 21:30）
- **構成（Fan-in Matrix）**:
  - **Fan-out** `generate-store`: 38 店舗 × 独立ジョブ、`max-parallel: 10`。`--skip-index` で `index.json` 更新を抑制。Supabase upsert は各ジョブ内で完結（`content_type='weekly'`, `is_published=true`）。生成 JSON を Artifact 保存（retention: 1日）。
  - **Fan-in** `collect-and-commit`: 全 Artifact を回収 → `index.json` を Python でマージ再構築 → テスト → Git commit 1回
- **出力先**: `frontend/content/insights/weekly/<store>/<date>.json` + `index.json`

#### Editorial Blog（`content_type='editorial'`, `is_published=false → true`）
- **トリガー**: LINE で「○○について分析して」などのメッセージ
- **生成**: `POST /api/line` → `insightFromRange.ts` → Gemini → Supabase（`is_published=false`）
- **承認**: LINE で「公開」「ok」等を送信 → `is_published=true` に更新 → `/blog/[public_slug]` の URL を返信
- **公開ページ**: `/blog/[slug]`（`content_type='editorial'`, `is_published=true` のみ表示）

#### その他
- Public Facts: GitHub Actions → `frontend/content/facts/public`
- Facts の debug notes は `NEXT_PUBLIC_SHOW_FACTS_DEBUG=1` のときのみ表示

### LINE 下書きパイプライン（要点）
- **n8n は使わない（廃止）**。司令塔は Next.js のみ。
- インサイト: `frontend/src/lib/blog/insightFromRange.ts`（今夜窓 → 全日フォールバック）
- 下書き生成: `frontend/src/lib/blog/draftGenerator.ts`（既定 Gemini モデルは **`gemini-2.5-flash`**）
- 意図解析: `frontend/src/lib/line/parseLineIntent.ts`（`draft` / `editorial_analysis` / `approve`）

## 動作確認の最小手順
- Backend: `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- Daily Report: Supabase に `content_type='daily'`, `is_published=true` の行があり `/reports/daily/<store>` で表示されること
- Weekly Report: `generate-weekly-insights.yml` 実行後、`/reports/weekly/<store>` で表示されること
- Editorial: LINE から分析依頼 → 承認 → `/blog/[slug]` で公開されること
- **LINE（本番）**: Vercel に LINE / Gemini / Supabase / `BACKEND_URL` が揃い、LINE からテキスト送信 → 返信・`blog_drafts` に行が増えること

## 既知の制限 / 注意
- 週次インサイト生成は `/api/range` の可用性に依存（Actions はタイムアウト/リトライあり）
- `/api/current` はローカル保存の最新値のため、Supabase の最新とは一致しない場合がある（**方針メモ**: `plan/API_CURRENT.md`）
- `/api/range` の **`limit` が小さい**と、その日の夜以外のサンプルしか取れずインサイトが偏る。**現行既定は 500**（`LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT`）。
- インサイトの **`avoid_time`** は「窓内で total が最小の時刻」（= **混雑が落ち着いている目安**）。読者向けはポジティブ表現を優先。
- Daily Report は `/api/cron/blog-draft` の 1リクエスト完了時間が Vercel の制約（~60秒）に近い場合がある。504 再発時は `plan/BLOG_CRON_ASYNC_FUTURE.md`。
