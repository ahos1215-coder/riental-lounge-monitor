# ARCHITECTURE
Last updated: 2026-04-12 (Round 9 + ML レジリエンス: disk cache fallback / 予測 UX 自動再試行)
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores/blog_drafts) → Flask API (**Render Starter $7/月**, 2025-12〜) → Next.js (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- Night window（19:00–05:00）: **店舗 UI** は `useStorePreviewData.ts`。**LINE 下書き**は `insightFromRange.ts`（Next サーバー）。Flask は夜窓を採らない
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は GitHub Actions で生成し、`frontend/content/*` にコミット
- コンテンツは 3種類に分類（`blog_drafts.content_type`）:
  - **`daily`**: GitHub Actions 定時 → Supabase → `/reports/daily/[store_slug]`
  - **`weekly`**: GitHub Actions 週次 → Supabase（`mdx_content` + `insight_json`）+ ファイル → `/reports/weekly/[store_slug]`（MDX + 定量データ統合表示）
  - **`editorial`**: LINE 指示 → Supabase（未公開）→ LINE 承認 → `/blog/[slug]`

## Data Flow

### 1) 収集
`multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む。cron-job.org が 5 分毎にトリガー（`CRON_SECRET` 認証）。`/tasks/tick` はレガシー。

**マルチブランド対応 (2026-04-17〜)**:
- **Oriental Lounge + ag (38店舗)**: `oriental-lounge.com/` トップページから 1 リクエストで全店舗の人数を SSR 抽出 (`src_brand="oriental"`)
- **相席屋 (6店舗)**: `aiseki-ya.com/` トップページから SSR でパーセンテージを抽出 → `(座席+VIP)×2 × %` で逆算 (`src_brand="aisekiya"`)
- 1 サイクル合計 **2 リクエストで全 44 店舗**を収集。リクエスト数 97% 削減 (旧: 38 個別リクエスト)
- 店舗マスタは `frontend/src/data/stores.json` を Python/Frontend 共通で参照（`brand` フィールドで分離）

### 2) Flask API
`/api/range` / `/api/current` / `/api/forecast_*` / `/api/forecast_today_multi` / `/api/megribi_score` / `/api/forecast_accuracy` を提供。`/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却。

**並列化パターン**: `range_multi`・`megribi_score`・`forecast_today_multi` は `ThreadPoolExecutor(max_workers=12)` で Supabase クエリ / ML 推論を並列実行。GIL 下でも I/O 待ち（HTTP）が支配的なため効果大。

**Flask プロセス内キャッシュ**: `forecast_today` / `forecast_today_multi` は TTL 60s のインメモリキャッシュを共有。CDN `s-maxage=60` と組み合わせ、最大遅延 ~2 分。

**ML モデルレジリエンス (2026-04-12〜)**: `model_registry.py` は 2 段階のフォールバックで Supabase Storage の一過性障害（接続リセット等）を吸収する:
1. **Disk cache fallback**: `_download_to_cache` がリトライ全敗した場合、`forecast_model_cache_dir` 上の既存ファイルが `FORECAST_MODEL_CACHE_MAX_AGE_SEC`（既定 7 日 = 604800）以内であれば fallback として採用し、警告ログ `model download failed; using existing disk cache as fallback` を出して継続する
2. **In-memory stale fallback**: `get_bundle` の TTL 切れリフレッシュが失敗しても、`self._bundles[store_key]` に前回の bundle が残っていればそれを返し続ける（`refresh_failed_using_stale_in_memory` 警告）。次回リフレッシュは `refresh_sec / 4`（最低 60s）に短縮して早期復旧を試みる

両 fallback の有効期限を超えた場合のみ本来の例外を伝播させる。

### 3) Next.js ページ・API Routes

| パス | データ取得元 |
|------|--------------|
| `/` | `/api/range` + `/api/megribi_score`（TOP 5 今夜のおすすめ）+ `getAllPostMetas()`（静的 MDX） |
| `/store/[id]` | `/api/range` + `/api/forecast_today`（**Promise.all 同時発火**。`useStorePreviewData.ts` は `forecast_today` が空配列だった場合 5s/15s/45s のバックオフで最大 3 回自動再試行し、`forecastStatus` を UI に伝える）+ `/api/reports/store-summary` |
| `/stores` | **request ordering 戦略**: ① `/api/range_multi` await → 部分カード即表示 → ② `/api/megribi_score` → ③ `/api/forecast_today_multi`（バッチ）を後続発火。単一 gunicorn worker でも ~1.5s で初期表示 |
| `/reports` | `/api/reports/list`（Supabase: 全店舗最新 Daily/Weekly メタ） |
| `/reports/daily/[store_slug]` | Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`） |
| `/reports/weekly/[store_slug]` | Supabase `blog_drafts`（`content_type='weekly'`, `is_published=true`）— `mdx_content` + `insight_json`（チャート・メトリクス・Good Windows） |
| `/insights/weekly/[store]` | **→ `/reports/weekly/[store]` に 301 リダイレクト**。旧ページは `frontend/content/insights/weekly/<store>/<date>.json`（fs）を読むが、リダイレクトが優先 |
| `/blog/[slug]` | Supabase `blog_drafts`（`content_type='editorial'`, `is_published=true`） |
| `/compare` | `/api/range_multi` + `/api/megribi_score` + `/api/forecast_today_multi`（最大3店舗並列比較） |
| `/mypage` | `/api/range` + `/api/forecast_today` + `/api/megribi_score`（お気に入り店舗分） |

#### GA4 アナリティクス（`NEXT_PUBLIC_GA_MEASUREMENT_ID` 設定時に有効）
- `GoogleAnalytics.tsx`: gtag.js ロード + SPA ページ遷移追跡（`usePathname` / `useSearchParams`）
- カスタムイベント: `store_view`、`report_read`、`favorite_add` / `favorite_remove`
- サーバーコンポーネント用: `ReportViewTracker.tsx`（null を返す "use client" ラッパー）

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
     ├─ 38店舗分の XGBoost モデル学習 → Supabase Storage upload
     ├─ 時系列 Train/Test Split（80/20）で Holdout 精度を測定
     ├─ Optuna HPO（30 trials/店舗、ML_OPTUNA_ENABLED=1 で制御）
     ├─ Early Stopping（n_estimators=300 上限、early_stopping_rounds=15）
     └─ Feature Importance + HPO best params を metadata.json に永続化

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
- `oriental/routes/common.py`（共通ヘルパー: `get_config` / `get_supabase_provider` / `resolve_store_id`）
- `oriental/routes/data.py`（/api/range, /api/current, /api/range_multi（ThreadPoolExecutor 並列化）, /api/second_venues）
- `oriental/routes/forecast.py`（/api/forecast_*, /api/forecast_today_multi, /api/megribi_score, /api/forecast_accuracy — ThreadPoolExecutor 並列化）
- `oriental/routes/tasks.py`（/tasks/multi_collect, /tasks/tick, CRON_SECRET 認証）
- `oriental/data/provider.py`（SupabaseLogsProvider, GoogleSheetProvider）
- `oriental/ml/forecast_service.py`（ML 推論オーケストレーション）
- `oriental/ml/megribi_score.py`（スコア算出 + good_windows）
- `oriental/ml/model_registry.py`（Supabase Storage からモデルロード）
- `oriental/ml/preprocess.py`（特徴量エンジニアリング — **22 FEATURE_COLUMNS、schema v5**。v4 の 21 + `extreme_weather`）
- `oriental/ml/model_xgb.py`（**LightGBM 優先ロード** + XGBoost フォールバック。ファイル名は import 互換のため維持）
- `multi_collect.py`（収集ロジック。Oriental Lounge トップページ + 相席屋トップページの2リクエストで全44店舗を取得）

### Frontend (Next.js)
- `frontend/src/app/api/*/route.ts`（backend proxy 8本 + SNS + LINE + cron）
- `frontend/src/app/api/forecast_today_multi/route.ts`（バッチ forecast proxy、CDN `s-maxage=60`）
- `frontend/src/app/api/forecast_accuracy/route.ts`（精度メトリクス proxy、CDN `s-maxage=3600`）
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
- `frontend/src/lib/line/parseLineIntent.ts`（draft / editorial_analysis / approve。scope: single / monthly / area_compare）
- `frontend/src/lib/supabase/blogDrafts.ts`（Supabase CRUD）
- `frontend/src/lib/dateFormat.ts`（JST 日時フォーマット共通ユーティリティ — レポートページ / API / チャートで共用）
- `frontend/src/app/config/stores.ts`（38 店舗マスタ）
- `frontend/src/components/StoreCard.tsx`（店舗カード。めぐりびスコアバッジ: 狙い目/様子見/他店へ）
- `frontend/src/components/WeeklyStoreCharts.tsx`（週次 Recharts チャート: 時系列 + Top Windows バーチャート。`/reports/weekly` と `/insights/weekly` で共有）
- `frontend/src/components/GoogleAnalytics.tsx`（GA4 Script ローダー + SPA トラッカー）
- `frontend/src/components/ReportViewTracker.tsx`（サーバーコンポーネント用 GA4 イベント発火）
- `frontend/src/lib/analytics.ts`（GA4 ヘルパー: sendEvent / sendPageView）
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
- `.github/workflows/check-pat-expiry.yml`（GitHub PAT 期限チェック + LINE 通知, 週次月曜 09:00 JST）
- `.github/workflows/e2e.yml`（Playwright E2E スモークテスト, PR + dispatch）
- `.github/workflows/notify-on-failure.yml`（失敗通知, 再利用ワークフロー）
- `.github/workflows/blog-request.yml`（手動ブログ依頼）

### Supabase
- `supabase/migrations/20260326000000_blog_drafts_content_split.sql`
- `supabase/migrations/20260412000000_blog_drafts_indexes.sql`（`updated_at DESC` + `(store_slug, created_at DESC)` インデックス）
