# STATUS
Last updated: 2026-03-28 (Round 4.5: パフォーマンス最適化 — ThreadPoolExecutor 並列化 + forecast_today_multi バッチ + request ordering)
Target commit: (see git)

## 現在動いている機能

### Backend (Flask / Render)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（**`store` / `limit` のみ**。Supabase は `ts.desc` 取得 → 返却は `ts.asc`、**サーバ側の夜窓フィルタなし**）
- `/api/range_multi`（**`stores=slug1,slug2,...` + `limit` 等**。Supabase のみ。店舗一覧の一括 range 取得用。**ThreadPoolExecutor(12) で並列取得**）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
  - **店舗別最適化モデル（ML 2.0）本番稼働中**。全38店舗で固有の重みを使った推論を有効化済み。
  - `model_registry.py` は `metadata.json` の `has_store_models` / `store_models` を検証し、**店舗別モデルを最優先でロード**。不整合時は明示エラー、未対応メタデータ時のみグローバルモデルへフォールバック。
  - **Flask プロセス内キャッシュ**: TTL 60s（`FORECAST_RESULT_CACHE_TTL`）。CDN キャッシュと合わせ最大遅延 ~2 分
- `/api/forecast_today_multi`（`?stores=slug1,slug2,...` 最大40店舗。**ThreadPoolExecutor(12) で並列実行** — 12店舗でも ~1-2s。Flask 内キャッシュ共有）
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/api/megribi_score`（全店舗 or 指定店舗の megribi_score を返す。`?store=` / `?stores=` 対応。Supabase backend 必須。**ThreadPoolExecutor(12) で並列取得 — 38店舗12s→<1s**）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口 → Supabase `logs`。デフォルト 202 Accepted + バックグラウンドスレッド実行。`?mode=sync` で旧同期モード。`/tasks/multi_collect/status` でステータス確認）
- `/tasks/tick` / `/tasks/collect` / `/tasks/seed`（レガシー・ローカル向け）
- `/tasks/update_second_venues`（任意。`GOOGLE_PLACES_API_KEY` がある場合のみ）
- 全 `/tasks/*` エンドポイントに `CRON_SECRET` 認証追加済み
- 旧プレースホルダ API（`/api/heatmap` 等）は削除済み

### Frontend (Next.js / Vercel)

#### ページルート（実装済み）
| パス | 概要 |
|------|------|
| `/` | トップ。「今夜のおすすめ」（megribi_score TOP 5）+ Last visited ミニチャート + ブログ新着 + ナビリンク |
| `/stores` | 全店舗一覧（12件/ページ・地域タブ・テキスト検索・**request ordering 戦略**: ① `range_multi` 最優先 await → 部分カード即表示 → ② `megribi_score` + ③ `forecast_today_multi` を後続発火。単一 gunicorn worker でも体感 ~1.5s で初期表示） |
| `/store/[id]` | 店舗詳細（リアルタイムカード・Recharts 時系列・ML 予測・レポート要約カード・関連店舗・**range + forecast 同時発火**） |
| `/reports` | **AI予測レポート統合一覧**（Daily/Weekly タブ切替・エリアフィルタ・店舗名検索。ヘッダー「AI予測」からリンク） |
| `/reports/daily` | `/reports` へリダイレクト |
| `/reports/daily/[store_slug]` | **Daily Report 個別**: 最新 `content_type='daily'`・`is_published=true`。Facts カード表示 |
| `/reports/weekly` | `/reports?tab=weekly` へリダイレクト |
| `/reports/weekly/[store_slug]` | **Weekly Report 個別**: 最新 `content_type='weekly'`・`is_published=true` |
| `/blog` | 編集ブログ一覧。AI予測レポート一覧への誘導バナー付き |
| `/blog/[slug]` | **editorial（`content_type='editorial'`, `is_published=true`）のみ**表示 |
| `/insights/weekly` | Weekly Insights インデックス（`index.json` から） |
| `/insights/weekly/[store]` | Weekly Insights 店舗別（`WeeklyStoreCharts.tsx`、Recharts `series_compact` 可視化） |
| `/mypage` | **ダッシュボード型マイページ**: お気に入り店舗リッチカード（リアルタイム人数・男女スパークライン・megribi_score・ML 予測サマリ・Daily/Weekly リンク）+ 閲覧履歴ピルタグ |

#### Next.js API Routes（13本）
| パス | 用途 |
|------|------|
| `/api/range` | Flask `/api/range` プロキシ（CDN `s-maxage` 付き） |
| `/api/range_multi` | Flask `/api/range_multi` プロキシ |
| `/api/forecast_today` | Flask `/api/forecast_today` プロキシ（CDN キャッシュ） |
| `/api/forecast_today_multi` | Flask `/api/forecast_today_multi` プロキシ（`?stores=slug1,slug2,...`、CDN `s-maxage=60`） |
| `/api/forecast_next_hour` | Flask `/api/forecast_next_hour` プロキシ |
| `/api/megribi_score` | Flask `/api/megribi_score` プロキシ（CDN `s-maxage=120`） |
| `/api/second_venues` | Flask `/api/second_venues` プロキシ |
| `/api/reports/list` | Supabase から全店舗の最新 Daily/Weekly レポートメタ一覧取得 |
| `/api/reports/store-summary` | 店舗詳細ページ用のレポート要約カード取得 |
| `/api/blog/latest-store-summary` | 店舗ごとの最新 Daily Report 要約 |
| `/api/cron/blog-draft` | Daily Report 生成（GHA matrix → Gemini → Supabase） |
| `/api/line` | LINE Messaging webhook（下書き/分析/承認） |
| `/api/sns/post` | X (Twitter) 投稿 API（OAuth 1.0a・dry_run 対応） |

#### その他フロントエンド機能
- **LINE Webhook（本番パス）**
  - `POST /api/line`: 署名検証 → **レート制限**（Upstash。グローバル/分＋ユーザーあたり下書き/時）→ テキスト解析 → 3 インテント:
    - **`draft` / `editorial_analysis`**: Flask `/api/range` + `/api/forecast_today` → `insightFromRange.ts` → Gemini MDX → Supabase `blog_drafts`（`content_type='editorial'`, `is_published=false`）
    - **`approve`**: 最新の未公開 editorial を `is_published=true` に更新 → `/blog/[public_slug]` URL を返信
- **OGP / メタデータ**: `metadataBase`、動的 OG 画像、全ページの `openGraph` / `twitter` 設定済み
- **Sitemap**: `/reports`（統合一覧）+ `/reports/daily/[store_slug]`（priority 0.85 / daily）+ `/reports/weekly/[store_slug]`（priority 0.8 / weekly）全店舗分。旧 `/blog/auto-*` は廃止
- **Recharts**: 全チャートを Chart.js → Recharts に統一済み（Round 3）。Chart.js 依存は完全削除
- **StoreCard**: データ未取得時のプレースホルダ（`—`・`0人`）を非表示化（Round 3）
- **ブログ frontmatter**: Zod 検証（`blogFrontmatter.ts` / `content.ts`）
- **CDN Cache-Control**: API proxy に `s-maxage` + `stale-while-revalidate` 設定。予測系（`forecast_today` / `forecast_next_hour`）は `s-maxage=60`（Flask TTL も 60s）、最大遅延 ~2 分

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
| `is_published` | boolean | `true` = 公開済み（daily/weekly は生成時 true、editorial は LINE 承認後 true） |
| `edition` | text | `evening_preview` / `late_update` / `weekly` / null |
| `public_slug` | text | `/blog/[slug]` の公開パス（`UNIQUE where not null`） |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |
| インデックス | --- | `facts_id` UNIQUE、`public_slug` UNIQUE (where not null)、`(content_type, is_published, store_slug, created_at)` |

Migration: `supabase/migrations/20260326000000_blog_drafts_content_split.sql`

### Content / Batch

#### Daily Report（`content_type='daily'`, `is_published=true`）
- **Workflow**: `.github/workflows/trigger-blog-cron.yml`（`schedule` 常駐 + `workflow_dispatch` 手動対応）
- **トリガー**: **GHA native schedule**（`cron: "0 9 * * *"` JST 18:00 → evening_preview、`cron: "30 12 * * *"` JST 21:30 → late_update）。cron-job.org 不要
- **構成**: 38店舗 × 独立 matrix ジョブ、`max-parallel: 15`、`continue-on-error: true`
- **エンドポイント**: `GET /api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
- **保存**: Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`）
- 失敗店舗のみ再実行: `retry-blog-draft-stores.yml`
- 部分失敗通知: `summarize-blog-matrix` → `notify-partial-blog-failures`（`OPS_NOTIFY_WEBHOOK_URL` 設定時）
- **X 自動投稿**: Daily Report 生成後、`x-auto-post.yml` が `workflow_run` で自動トリガー。許可店舗のみ投稿

#### Weekly Report（`content_type='weekly'`, `is_published=true`）
- **Workflow**: `.github/workflows/generate-weekly-insights.yml`（毎週水曜 06:30 JST = UTC 火曜 21:30）
- **構成（Fan-in Matrix）**:
  - **Fan-out** `generate-store`: 38 店舗 × 独立ジョブ、`max-parallel: 10`。`--skip-index` で `index.json` 更新を抑制。Supabase upsert は各ジョブ内で完結
  - **Fan-in** `collect-and-commit`: 全 Artifact を回収 → `index.json` マージ再構築 → Git commit 1回
- **出力先**: `frontend/content/insights/weekly/<store>/<date>.json` + `index.json`

#### Editorial Blog（`content_type='editorial'`, `is_published=false → true`）
- **トリガー**: LINE で「○○について分析して」などのメッセージ
- **生成**: `POST /api/line` → `insightFromRange.ts` → Gemini → Supabase（`is_published=false`）
- **承認**: LINE で「公開」「ok」等を送信 → `is_published=true` に更新 → `/blog/[public_slug]` の URL を返信

#### X (Twitter) 自動投稿
- **Workflow**: `.github/workflows/x-auto-post.yml`
- **トリガー**: `trigger-blog-cron.yml` 完了後に `workflow_run` で自動実行。手動 `workflow_dispatch` も対応
- **投稿先**: `/api/sns/post`（OAuth 1.0a 署名、リトライ機構付き）
- **対象**: `SNS_POST_ALLOWED_STORE_SLUGS`（CSV）+ nagasaki のみ。dry_run デフォルト
- **環境変数**: `X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` / `SNS_POST_SECRET`

#### その他
- Public Facts: GitHub Actions → `frontend/content/facts/public`
- Facts の debug notes は `NEXT_PUBLIC_SHOW_FACTS_DEBUG=1` のときのみ表示

### GitHub Actions ワークフロー一覧

| ファイル | 用途 | トリガー |
|----------|------|----------|
| `trigger-blog-cron.yml` | Daily Report 38店舗 matrix | `schedule`（09:00/12:30 UTC）+ `workflow_dispatch` |
| `generate-weekly-insights.yml` | Weekly Report Fan-in Matrix | `schedule`（水曜 UTC 21:30）+ dispatch |
| `generate-public-facts.yml` | Public Facts 生成 + Git commit | `schedule`（毎日 UTC 00:30）+ dispatch |
| `train-ml-model.yml` | ML モデル学習 + Supabase Storage | `schedule`（毎日 UTC 20:30）+ dispatch |
| `x-auto-post.yml` | X 自動投稿 | `workflow_run`（Daily 完了後）+ dispatch |
| `retry-blog-draft-stores.yml` | Daily 失敗店舗再実行 | `workflow_dispatch` |
| `blog-request.yml` | 手動ブログ依頼 | `workflow_dispatch` |
| `blog-ci.yml` | フロント CI（type-check / build） | push |
| `notify-on-failure.yml` | 失敗通知（再利用） | `workflow_call` |

### LINE 下書きパイプライン（要点）
- **n8n は使わない（廃止）**。司令塔は Next.js のみ
- インサイト: `frontend/src/lib/blog/insightFromRange.ts`（今夜窓 → 全日フォールバック）
- 下書き生成: `frontend/src/lib/blog/draftGenerator.ts`（既定 Gemini モデルは **`gemini-2.5-flash`**）
- 意図解析: `frontend/src/lib/line/parseLineIntent.ts`（`draft` / `editorial_analysis` / `approve`）

### Cron 構成（外部トリガー）

| サービス | 対象 | JST | 備考 |
|----------|------|-----|------|
| GHA schedule | `trigger-blog-cron.yml` | 18:00 / 21:30 | UTC 09:00 / 12:30。cron-job.org 不要 |
| cron-job.org | `/tasks/multi_collect` | 15分毎（営業時間帯） | `CRON_SECRET` 認証 |
| GHA schedule | `train-ml-model.yml` | 05:30 | UTC 20:30 |
| GHA schedule | `generate-public-facts.yml` | 09:30 | UTC 00:30 |
| GHA schedule | `generate-weekly-insights.yml` | 水曜 06:30 | UTC 火曜 21:30 |

## 動作確認の最小手順
- Backend: `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- Daily Report: Supabase に `content_type='daily'`, `is_published=true` の行があり `/reports/daily/<store>` で表示されること
- Weekly Report: `generate-weekly-insights.yml` 実行後、`/reports/weekly/<store>` で表示されること
- Editorial: LINE から分析依頼 → 承認 → `/blog/[slug]` で公開されること
- **LINE（本番）**: Vercel に LINE / Gemini / Supabase / `BACKEND_URL` が揃い、LINE からテキスト送信 → 返信・`blog_drafts` に行が増えること
- 統合レポート: `/reports` でタブ切替・検索・フィルタが機能すること
- マイページ: `/mypage` でお気に入り店舗のリッチカードが表示されること
- X 投稿: `x-auto-post.yml` を `dry_run=true` で実行し、ログに投稿テキストが出ること

## 既知の制限 / 注意
- 週次インサイト生成は `/api/range` の可用性に依存（Actions はタイムアウト/リトライあり）
- `/api/current` はローカル保存の最新値のため、Supabase の最新とは一致しない場合がある（**方針メモ**: `plan/API_CURRENT.md`）
- `/api/range` の **`limit` が小さい**と、その日の夜以外のサンプルしか取れずインサイトが偏る。**現行既定は 500**（`LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT`）
- Daily Report は `/api/cron/blog-draft` の 1リクエスト完了時間が Vercel の制約（~60秒）に近い場合がある。504 再発時は `plan/BLOG_CRON_ASYNC_FUTURE.md`
- Open-Meteo 天気 API は 429 レート制限あり。リクエスト間隔を十分空けること（天気データは disk cache + TTL で 1 時間に 1 回取得）

## 識別済みデッドコード（未削除）
- `frontend/src/components/PreviewHeader.tsx` — 未参照
- `frontend/src/components/home/HomeHeroSection.tsx` — 未参照
- `frontend/src/app/components/DashboardPreview.tsx` — 未参照
- `frontend/src/app/components/DebugPanel.tsx` / `DebugSection.tsx` — 相互参照のみ
- `frontend/src/app/types/range.ts` — 未参照
- `frontend/src/app/api/forecast_common.ts` — 未参照（レガシー）
- `frontend/src/app/blog/_data.ts` — 未参照（旧データソース）
- `frontend/src/app/blog/` 配下の `.bak` ファイル（18件） — バックアップ残骸
