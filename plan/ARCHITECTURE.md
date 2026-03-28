# ARCHITECTURE
Last updated: 2026-03-28 (Round 4.5: パフォーマンス最適化)
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores/blog_drafts) → Flask API (**Render Starter $7/月**, 2025-12〜) → Next.js (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- Night window（19:00–05:00）: **店舗 UI** は `useStorePreviewData.ts`。**LINE 下書き**は `insightFromRange.ts`（Next サーバー）。Flask は夜窓を採らない
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は GitHub Actions で生成し、`frontend/content/*` にコミット
- コンテンツは 3種類に分類（`blog_drafts.content_type`）:
  - **`daily`**: GitHub Actions 定時 → Supabase → `/reports/daily/[store_slug]`
  - **`weekly`**: GitHub Actions 週次 → Supabase + ファイル → `/reports/weekly/[store_slug]`
  - **`editorial`**: LINE 指示 → Supabase（未公開）→ LINE 承認 → `/blog/[slug]`

## Data Flow

### 1) 収集
`multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む。cron-job.org が 15 分毎にトリガー（`CRON_SECRET` 認証）。`/tasks/tick` はレガシー。

### 2) Flask API
`/api/range` / `/api/current` / `/api/forecast_*` / `/api/forecast_today_multi` / `/api/megribi_score` を提供。`/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却。

**並列化パターン**: `range_multi`・`megribi_score`・`forecast_today_multi` は `ThreadPoolExecutor(max_workers=12)` で Supabase クエリ / ML 推論を並列実行。GIL 下でも I/O 待ち（HTTP）が支配的なため効果大。

**Flask プロセス内キャッシュ**: `forecast_today` / `forecast_today_multi` は TTL 60s のインメモリキャッシュを共有。CDN `s-maxage=60` と組み合わせ、最大遅延 ~2 分。

### 3) Next.js ページ・API Routes

| パス | データ取得元 |
|------|--------------|
| `/` | `/api/range` + `/api/megribi_score`（TOP 5 今夜のおすすめ）+ `getAllPostMetas()`（静的 MDX） |
| `/store/[id]` | `/api/range` + `/api/forecast_today`（**Promise.all 同時発火**）+ `/api/reports/store-summary` |
| `/stores` | **request ordering 戦略**: ① `/api/range_multi` await → 部分カード即表示 → ② `/api/megribi_score` → ③ `/api/forecast_today_multi`（バッチ）を後続発火。単一 gunicorn worker でも ~1.5s で初期表示 |
| `/reports` | `/api/reports/list`（Supabase: 全店舗最新 Daily/Weekly メタ） |
| `/reports/daily/[store_slug]` | Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`） |
| `/reports/weekly/[store_slug]` | Supabase `blog_drafts`（`content_type='weekly'`, `is_published=true`） |
| `/insights/weekly/[store]` | `frontend/content/insights/weekly/<store>/<date>.json`（fs） |
| `/blog/[slug]` | Supabase `blog_drafts`（`content_type='editorial'`, `is_published=true`） |
| `/mypage` | `/api/range` + `/api/forecast_today` + `/api/megribi_score`（お気に入り店舗分） |

#### `/stores` ページのリクエスト順序（単一 worker 対策）

Render Starter プラン（$7/月、2025-12 移行済み）の gunicorn は `--workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-2}`。スリープなし・永続ディスク対応。ただし同一ワーカーに複数リクエストが入るとシリアル処理になる。重い forecast_today_multi（~7s）が先に処理されると range_multi（~1s）がブロックされ、ユーザーは何も見えない状態が長く続く。

**解決**: フロントエンドのリクエスト発火順を制御:
1. `range_multi` を **最優先で await** — 部分カード（人数・チャート）を即表示
2. `megribi_score`（軽量 ~0.5s）を発火
3. `forecast_today_multi`（重い ~2-7s）を最後に発火
4. forecast 結果が返ったらカードにマージ（プログレッシブレンダリング）

### 4) GitHub Actions バッチ

```
Daily Report（毎日 18:00 / 21:30 JST — GHA native schedule）:
  trigger-blog-cron.yml
  └─ matrix: 38 store × 独立ジョブ (max-parallel: 15)
     └─ GET /api/cron/blog-draft?store=<slug>&edition=...
        └─ Supabase blog_drafts (content_type='daily', is_published=true)
  x-auto-post.yml (workflow_run: trigger-blog-cron 完了後)
  └─ 許可店舗ごとに POST /api/sns/post → X (Twitter) 投稿

Weekly Report（毎週水曜 06:30 JST — GHA schedule）:
  generate-weekly-insights.yml [Fan-in 構成]
  ├─ generate-store: 38 store × 独立ジョブ (max-parallel: 10)
  │   ├─ generate_weekly_insights.py --stores <one_store> --skip-index
  │   ├─ Supabase upsert (content_type='weekly', is_published=true)
  │   └─ upload Artifact: weekly-<store>/
  └─ collect-and-commit: Fan-in
      ├─ download all Artifacts
      ├─ rebuild index.json (Python inline)
      ├─ pytest
      └─ git commit & push (1回のみ)

ML Model Training（毎日 05:30 JST — GHA schedule）:
  train-ml-model.yml
  └─ scripts/train_ml_model.py
     └─ 38店舗分の XGBoost モデル学習 → Supabase Storage upload

Public Facts（毎日 09:30 JST — GHA schedule）:
  generate-public-facts.yml
  └─ frontend/scripts/generate-public-facts.mjs
     └─ frontend/content/facts/public/ に JSON 出力 → git commit
```

### 5) LINE 承認フロー（Editorial）
```
LINE メッセージ（「分析して」等）
  → POST /api/line
    → parseLineIntent: editorial_analysis
    → /api/range + /api/forecast_today (BACKEND_URL 経由)
    → insightFromRange.ts
    → draftGenerator.ts (Gemini)
    → Supabase blog_drafts (content_type='editorial', is_published=false)
    → LINE 返信（「確認してから公開してください」）

LINE メッセージ（「公開」「ok」等）
  → POST /api/line
    → parseLineIntent: approve
    → blog_drafts の is_published を true に更新
    → LINE 返信（/blog/[public_slug] の URL）
```

### 6) X (Twitter) 自動投稿フロー
```
trigger-blog-cron.yml (Daily Report) 完了
  → x-auto-post.yml (workflow_run トリガー)
    → 許可店舗リストを決定（SNS_POST_ALLOWED_STORE_SLUGS or デフォルト）
    → 各店舗について:
       POST /api/sns/post
         → OAuth 1.0a 署名生成
         → POST https://api.twitter.com/2/tweets
         → リトライ機構（429/5xx で exponential backoff）
         → sleep 2s between posts
```

## Contracts / Constraints
- `/api/range` の公開契約は `store` + `limit` のみ
  - server-side の時間フィルタ禁止。night window は **店舗 UI のフロント**および **LINE 用 `insightFromRange.ts`** で実施
- Secrets は環境変数のみ（`NEXT_PUBLIC_*` に秘密を入れない）
- 既存エンドポイント互換性を維持（/healthz, /api/meta, /api/current, /api/range, /api/forecast_*, /tasks/*）
- Second venues は map-link 方式を維持（Places API 依存に戻さない）
- Supabase への書き込みは Next.js サーバー側からのみ（`SUPABASE_SERVICE_ROLE_KEY` はサーバー限定）
- X 投稿は `SNS_POST_SECRET` による Bearer 認証必須。dry_run デフォルト

## Blog Cron Scale Strategy（実装済み）
- **Daily**: GitHub Actions `trigger-blog-cron.yml` が `matrix` で 38店舗を **`max-parallel: 15`** で並列処理。504 が出た店舗は `continue-on-error` + `retry-blog-draft-stores.yml` で再実行
- **Weekly**: `generate-weekly-insights.yml` が Fan-in Matrix 構成。Fan-out（`max-parallel: 10`）→ Fan-in で `index.json` 一元マージ

## Key Files

### Backend (Python / Flask)
- `oriental/routes/data.py`（/api/range, /api/current, /api/range_multi（ThreadPoolExecutor 並列化）, /api/second_venues）
- `oriental/routes/forecast.py`（/api/forecast_*, /api/forecast_today_multi, /api/megribi_score — ThreadPoolExecutor 並列化）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick, CRON_SECRET 認証）
- `oriental/data/provider.py`（SupabaseLogsProvider, GoogleSheetProvider）
- `oriental/ml/forecast_service.py`（ML 推論オーケストレーション）
- `oriental/ml/megribi_score.py`（スコア算出 + good_windows）
- `oriental/ml/model_registry.py`（Supabase Storage からモデルロード）
- `oriental/ml/preprocess.py`（特徴量エンジニアリング）
- `multi_collect.py`（収集ロジック）

### Frontend (Next.js)
- `frontend/src/app/api/*/route.ts`（backend proxy 7本 + SNS + LINE + cron）
- `frontend/src/app/api/forecast_today_multi/route.ts`（バッチ forecast proxy、CDN `s-maxage=60`）
- `frontend/src/app/reports/page.tsx`（統合レポート一覧: reports-client.tsx）
- `frontend/src/app/reports/daily/[store_slug]/page.tsx`（Daily Report 個別）
- `frontend/src/app/reports/weekly/[store_slug]/page.tsx`（Weekly Report 個別）
- `frontend/src/app/mypage/mypage-client.tsx`（ダッシュボード型マイページ）
- `frontend/src/app/home-client.tsx`（トップ: megribi_score + last visited）
- `frontend/src/app/stores/stores-list-client.tsx`（店舗一覧 — request ordering 戦略）
- `frontend/src/app/store/[id]/page.tsx`（店舗詳細 — range+forecast 同時発火）
- `frontend/src/lib/blog/insightFromRange.ts`（LINE 用インサイト・窓計算）
- `frontend/src/lib/blog/draftGenerator.ts`（Gemini 下書き）
- `frontend/src/lib/blog/runBlogDraftPipeline.ts`（source → content_type 導出）
- `frontend/src/lib/line/parseLineIntent.ts`（draft / editorial_analysis / approve）
- `frontend/src/lib/supabase/blogDrafts.ts`（Supabase CRUD）
- `frontend/src/app/config/stores.ts`（38 店舗マスタ）
- `frontend/src/components/StoreCard.tsx`（店舗カード）
- `frontend/src/components/MeguribiHeader.tsx`（グローバルヘッダー）

### Content / Batch
- `scripts/generate_weekly_insights.py`（`--skip-index` 対応）
- `scripts/train_ml_model.py`（日次 ML 学習）
- `frontend/scripts/generate-public-facts.mjs`
- `frontend/content/insights/weekly`（JSON + index.json）
- `frontend/content/facts/public`

### Workflows
- `.github/workflows/trigger-blog-cron.yml`（Daily Report, matrix max-parallel: 15）
- `.github/workflows/generate-weekly-insights.yml`（Weekly Report, Fan-in Matrix）
- `.github/workflows/train-ml-model.yml`（ML 日次学習）
- `.github/workflows/x-auto-post.yml`（X 自動投稿, workflow_run + dispatch）
- `.github/workflows/generate-public-facts.yml`（Facts 生成）
- `.github/workflows/retry-blog-draft-stores.yml`（Daily 失敗再実行）
- `.github/workflows/blog-ci.yml`（フロント CI）
- `.github/workflows/notify-on-failure.yml`（失敗通知, 再利用ワークフロー）
- `.github/workflows/blog-request.yml`（手動ブログ依頼）

### Supabase
- `supabase/migrations/20260326000000_blog_drafts_content_split.sql`
