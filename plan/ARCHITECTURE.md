# ARCHITECTURE
Last updated: 2026-07-11（Batch B3: 店舗数43・Daily/Weekly のローカル Ollama 移行・schema v7・LightGBM表記を実コードに合わせて修正。ML v6 本番反映当時の記述はそのまま履歴として残し、末尾に 2026-07 時点の差分を追記）
Target commit: (see git)

## Overview
- Stack: Supabase (logs/stores/blog_drafts) → Flask API (**Render Starter $7/月**, 2025-12〜) → Next.js (Vercel)
- Source of truth: Supabase `logs`（Google Sheet / GAS は legacy fallback）
- 店舗数: **43**（Oriental Lounge + ag 38 + 相席屋 5）。正本は `oriental/utils/stores.py` の `ALL_STORE_IDS` と `frontend/src/data/stores.json`（行数一致必須）。
- Night window（19:00–05:00）: **店舗 UI** は `useStorePreviewData.ts`。**LINE 下書き**は `insightFromRange.ts`（Next サーバー）。Flask は夜窓を採らない
- Second venues は map-link 方式（frontend でリンク生成）
- Insights / Facts は生成し、`frontend/content/*` にコミット。**Daily/Weekly Report は 2026-07〜ローカル Ollama が主経路**（GitHub Actions は emergency 用の `workflow_dispatch` のみ。詳細は本ファイル §4 と `docs/LOCAL_LLM_SETUP.md`）
- コンテンツは 3種類に分類（`blog_drafts.content_type`）:
  - **`daily`**: ローカル Ollama 定時（主）/ GHA `workflow_dispatch`（緊急時のみ）→ Supabase → `/reports/daily/[store_slug]`
  - **`weekly`**: ローカル Ollama 定時（主）/ GHA `workflow_dispatch`（緊急時のみ）→ Supabase（`mdx_content` + `insight_json`）+ ファイル → `/reports/weekly/[store_slug]`（MDX + 定量データ統合表示）
  - **`editorial`**: LINE 指示 → Supabase（未公開）→ LINE 承認 → `/blog/[slug]`

## Data Flow

### 1) 収集
`multi_collect.py` または `/tasks/multi_collect` が Supabase `logs` に書き込む。cron-job.org が 5 分毎にトリガー（`CRON_SECRET` 認証）。`/tasks/tick` はレガシー。

**マルチブランド対応 (2026-04-17〜)**:
- **Oriental Lounge + ag (38店舗)**: `oriental-lounge.com/` トップページから 1 リクエストで全店舗の人数を SSR 抽出 (`src_brand="oriental"`)
- **相席屋 (5店舗)**: `aiseki-ya.com/` トップページから SSR でパーセンテージを抽出 → `(座席+VIP)×2 × %` で逆算 (`src_brand="aisekiya"`)。旧6店舗から `ay_niigata` 廃止で5店舗（`oriental/utils/stores.py` の `AISEKIYA_STORE_IDS`）。
- 1 サイクル合計 **2 リクエストで全 43 店舗**を収集。リクエスト数 97% 削減 (旧: 38 個別リクエスト)
- 店舗マスタは `frontend/src/data/stores.json` を Python/Frontend 共通で参照（`brand` フィールドで分離）

### 2) Flask API
`/api/range` / `/api/current` / `/api/forecast_*` / `/api/forecast_today_multi` / `/api/megribi_score` / `/api/forecast_accuracy` / `/api/holiday_status` を提供。`/api/range` は Supabase を `ts.desc` で取得し `ts.asc` で返却。

`/api/holiday_status` (2026-05-03〜) は `oriental/ml/holiday_calendar.py` の `get_holiday_block` / `is_long_holiday` をラップ。任意の日付について「連続休業日数 + ブロック内位置 + 連休フラグ + 表示ラベル」を返す。フロントの `LongHolidayBanner` と、ML の `holiday_block_*` 特徴量で同じロジックを共有する。

**並列化パターン**: `range_multi`・`megribi_score`・`forecast_today_multi` は `ThreadPoolExecutor(max_workers=12)` で Supabase クエリ / ML 推論を並列実行。GIL 下でも I/O 待ち（HTTP）が支配的なため効果大。

**Flask プロセス内キャッシュ**: `forecast_today` / `forecast_today_multi` は TTL 60s のインメモリキャッシュを共有。CDN `s-maxage=60` と組み合わせ、最大遅延 ~2 分。

**Cold-start 緩和 (2026-05-05〜)**: 低トラフィック時間帯に Render Flask が冷えて初回 TTFB が 9-10 秒に達していた問題を、外部の **UptimeRobot 無料枠で 5 経路を 5 分間隔 ping** することで解消。詳細・運用ノートは `plan/STATUS.md` の「運用 / モニタリング」セクションを参照。実測効果: `/api/forecast_today` TTFB 9.43s → 2.02s。

**ML モデルレジリエンス (2026-04-12〜)**: `model_registry.py` は 2 段階のフォールバックで Supabase Storage の一過性障害（接続リセット等）を吸収する:
1. **Disk cache fallback**: `_download_to_cache` がリトライ全敗した場合、`forecast_model_cache_dir` 上の既存ファイルが `FORECAST_MODEL_CACHE_MAX_AGE_SEC`（既定 7 日 = 604800）以内であれば fallback として採用し、警告ログ `model download failed; using existing disk cache as fallback` を出して継続する
2. **In-memory stale fallback**: `get_bundle` の TTL 切れリフレッシュが失敗しても、`self._bundles[store_key]` に前回の bundle が残っていればそれを返し続ける（`refresh_failed_using_stale_in_memory` 警告）。次回リフレッシュは `refresh_sec / 4`（最低 60s）に短縮して早期復旧を試みる

両 fallback の有効期限を超えた場合のみ本来の例外を伝播させる。

### 3) Next.js ページ・API Routes

| パス | データ取得元 |
|------|--------------|
| `/` | `/api/range` + `/api/megribi_score`（TOP 5 今夜のおすすめ）+ `getAllPostMetas()`（静的 MDX） |
| `/store/[id]` | `/api/range` + `/api/forecast_today`（**Promise.all 同時発火**。`useStorePreviewData.ts` は `forecast_today` が空配列だった場合 5s/15s/45s のバックオフで最大 3 回自動再試行し、`forecastStatus` を UI に伝える）+ `/api/reports/store-summary` + `/api/holiday_status` (`LongHolidayBanner`) + `/api/blog/latest-store-summary` (今日の傾向まとめ) |
| `/stores` | **request ordering 戦略**: ① `/api/range_multi` await → 部分カード即表示 → ② `/api/megribi_score` → ③ `/api/forecast_today_multi`（バッチ）を後続発火。単一 gunicorn worker でも ~1.5s で初期表示 |
| `/reports` | `/api/reports/list`（Supabase: 全店舗最新 Daily/Weekly メタ） |
| `/reports/daily/[store_slug]` | Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`） |
| `/reports/weekly/[store_slug]` | Supabase `blog_drafts`（`content_type='weekly'`, `is_published=true`）— `mdx_content` + `insight_json` (v2 redesign 2026-05〜): `daily_summary` (日別サマリ) / `metric_interpretations` (Phase A 解釈) / `day_hour_heatmap` (Phase B ヒートマップ) / `last_week_summary` + `next_week_forecast` (Phase C AI 自然文 — Markdown 箇条書き、フロントは ReactMarkdown でレンダ) / `next_week_recommendations` (Phase D 来週狙い目 TOP 3) / 既存の `top_windows` / `metrics` |
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

### 4) 定時バッチ（2026-07〜 ローカル Ollama が主経路 / GitHub Actions は補助・緊急用）

> **重要**: Daily Report と Weekly Report は 2026-07 に Gemini + GitHub Actions から
> **オーナーPC（Windows 常時起動・GPU共有）のローカル Ollama（`gemma4:e4b`）** へ主経路が移行済み。
> 該当 GHA ワークフローは `schedule:` をコメントアウト済みで `workflow_dispatch`（緊急用）のみ有効。
> ローカルと GHA を同時に定時実行すると同じ `facts_id`/`blog_drafts` 行を奪い合う（二重生成）ため、
> 手動実行時は必ずローカルジョブが動いていない時間帯に行うこと。詳細手順は `docs/LOCAL_LLM_SETUP.md`。

```
Daily Report（毎日 18:00 / 21:30 JST）:
  【主】ローカル Task Scheduler MEGRIBI-daily-evening / MEGRIBI-daily-late
  └─ scripts/local_report_job.py --stores all --edition <evening_preview|late_update> --mode publish
     └─ Ollama (gemma4:e4b, http://localhost:11434) で本文生成 → Supabase blog_drafts upsert
        (content_type='daily', is_published=true。失敗時は本文空 + is_published=false + error_message)
  【緊急用のみ・通常は無効】trigger-blog-cron.yml（GHA, workflow_dispatch）
  └─ matrix: オリエンタル 38 store × 独立ジョブ (max-parallel: 5)。相席屋5店舗は対象外。
     └─ GET /api/cron/blog-draft?store=<slug>&edition=... → Gemini → Supabase blog_drafts
  x-auto-post.yml (workflow_run: trigger-blog-cron 完了後。GHA 経路使用時のみ発火)
  └─ 許可店舗ごとに POST /api/sns/post → X (Twitter) 投稿

Weekly Report（毎週水曜 06:30 JST）:
  【主】ローカル Task Scheduler MEGRIBI-weekly
  └─ scripts/run_weekly_local.ps1 -Stores all
     └─ generate_weekly_insights.py --stores all（INSIGHTS_LLM_BACKEND=ollama, gemma4:e4b）
        全43店舗を単一プロセスで順次処理（Fan-in Matrix は使わない）
        ├─ /api/range で過去データ取得 → find_good_windows / top_windows
        ├─ v2: _build_day_hour_heatmap (7 曜日 × 10 時間、0-4時は前日の夜セッション扱い)
        ├─ v2: _build_daily_summary (7 夜分の avg/peak、夜セッション基準)
        ├─ v2: _compute_metric_interpretations (Phase A ラベル)
        ├─ v2: _derive_next_week_recommendations (Phase D ヒートマップ上位 3 セル)
        ├─ v2: _generate_ai_commentary (Phase C, Ollama。失敗時は既存 Supabase レコードの
        │        文章を保持して上書き消失防止)
        └─ Supabase upsert (content_type='weekly', is_published=true) + index.json 直接更新
  【緊急用のみ・通常は無効】generate-weekly-insights.yml（GHA, workflow_dispatch）[Fan-in Matrix 構成]
  ├─ generate-store: オリエンタル 38 store × 独立ジョブ (max-parallel: 10)。相席屋5店舗は対象外。
  │   └─ generate_weekly_insights.py --stores <one_store> --skip-index（INSIGHTS_LLM_BACKEND=gemini）
  └─ collect-and-commit: Fan-in（全 Artifact 回収 → index.json 再構築 → pytest → git commit & push）

ML Model Training（毎日 05:30 JST・毎週月曜 07:00 JST — GHA schedule。これは移行対象外、引き続き GHA が本流）:
  train-ml-model.yml
  └─ scripts/train_ml_model.py
     ├─ 日次 (05:30 JST): 固定パラメータで再学習のみ（Optuna なし。GHA 実行時間 90% 削減）
     ├─ 週次 (月曜 07:00 JST): Optuna HPO あり（30 trials/店舗）
     ├─ `oriental/utils/stores.py` の ALL_STORE_IDS（43店舗）を allow-list に LightGBM モデル学習
     │   → Supabase Storage (`ml-models/forecast/latest/`) へ upload
     ├─ 時系列 Train/Test Split（80/20）で Holdout 精度を測定
     ├─ Early Stopping（n_estimators=300 上限、early_stopping_rounds=15）
     ├─ Champion/Challenger gate（`ML_GATE_MAX_REGRESSION_PCT`）+ 稼働店舗 stale guard
     └─ Feature Importance + HPO best params を metadata.json に永続化（schema_version=v7）

Forecast v2 shadow pipeline（答え合わせ・GHA schedule。本番配信には影響しない）:
  forecast-accuracy-track.yml: snapshot 18:10 JST（今夜の予測を保存）/ score 06:10 JST（前夜の実測と採点）
  build-templates.yml: 07:30 JST（スコアリング後）で forecast/templates_v2.json を再生成
  → いずれも Supabase Storage の `<bucket>/accuracy/*` 配下に読み書き。詳細は `plan/FORECAST_V2.md` / `plan/FORECAST_ACCURACY.md`

CDN warming（営業ピーク帯 19:00-23:50 JST・10分毎）:
  【主】ローカル Task Scheduler MEGRIBI-warm-cdn → scripts/warm_cdn_local.py（stdlib のみ）
  【バックアップ】warm-cdn.yml（GHA schedule）— 実測で発火率 8.3% のため保険としてのみ残す
  → 詳細は `plan/CDN_WARMING_LOCAL.md`

Public Facts（毎日 09:30 JST — GHA schedule。これは移行対象外）:
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

## Blog Cron Scale Strategy
- **通常運用（2026-07〜）**: ローカル Ollama が単一プロセスで全43店舗を順次処理するため matrix/並列度の概念は無い。速度は `scripts/tune_local_llm.py` の推奨 options（GPU 全層オフロード等）で調整する。
- **緊急時 GHA 経路（`workflow_dispatch`、Gemini 使用・オリエンタル38店舗のみ）**:
  - **Daily**: `trigger-blog-cron.yml` が `matrix` で **`max-parallel: 5`** (`989637e`, 2026-04 で 15 → 5 に削減 — Gemini 無料枠 RPM 対策) で並列処理。504 が出た店舗は `continue-on-error` + `retry-blog-draft-stores.yml` で再実行
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
- `oriental/ml/preprocess.py`（特徴量エンジニアリング — **24 FEATURE_COLUMNS、schema v7** (2026-07〜)。列数は v6 (2026-05-03〜) と同じ24列のまま。v7 は列追加ではなく `total_slope_30min` のターゲットリーク修正で、v6 モデルとは非互換・再学習必須）
- `oriental/ml/holiday_calendar.py`（**2026-05-03〜**。連休判定のロジック単一ソース。`is_off_day` (土日 + 法定祝日 + 振替休日 + お盆 8/13-15 + 年末年始 12/29-1/3) / `get_holiday_block` (連続休業ブロックの長さと位置) / `is_long_holiday` (block_length>=4)。preprocess.py と /api/holiday_status の双方が import）
- `oriental/ml/model_xgb.py`（**LightGBM 優先ロード** + XGBoost フォールバック。ファイル名は import 互換のため維持。「XGBoost」という名前だが実体は LightGBM ── 改名しないこと）
- `oriental/utils/stores.py`（`STORE_IDS`(38) + `AISEKIYA_STORE_IDS`(5) = `ALL_STORE_IDS`(**43**)。store 解決・ML の allow-list の正本）
- `multi_collect.py`（収集ロジック。Oriental Lounge トップページ + 相席屋トップページの2リクエストで全43店舗を取得）

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
- `frontend/src/app/config/stores.ts`（43 店舗マスタ。`stores.json` を brand フィルタ無しでそのまま読み込む）
- `frontend/src/components/StoreCard.tsx`（店舗カード。めぐりびスコアバッジ: 狙い目/様子見/他店へ）
- `frontend/src/components/WeeklyStoreCharts.tsx`（週次 Recharts チャート。**v2 (2026-05〜) で時系列折れ線 + 賑わいスコアバーは削除**、現在は実質未使用 — `TopWindowChart` 型のみエクスポート）
- `frontend/src/components/WeeklyHeatmap.tsx`（**2026-05-03〜**。曜日 × 時間帯ヒートマップ。10 行 (時間 19-04) × 7 列 (曜日 月-日)。データセット内最大値で正規化 + ガンマ 0.55 + 多色グラデ (青 220° → 紫 290° → 桃赤 345°) で混雑度差を強調。0-4 時は前日の夜セッションとして集計済みの注記あり）
- `frontend/src/components/WeeklySummary.tsx`（**2026-05-03〜**。直近 7 夜分の日別サマリ。各夜 19:00-翌04:59 を 1 単位で avg/peak 混雑度をバー表示、一番賑わった夜を強調）
- `frontend/src/components/store/LongHolidayBanner.tsx`（**2026-05-03〜**。`/store/[id]` の `PreviewMainSection` 内、タイムラインと「今日の傾向まとめ」の間に表示。`/api/holiday_status` を呼んで `is_long_holiday=true` のときのみ表示）
- `frontend/src/components/store/LatestForecastSummaryCard.tsx`（「今日の傾向まとめ」カード。`/api/blog/latest-store-summary` から最新 Daily Report の bullets を抜粋）
- `frontend/src/components/GoogleAnalytics.tsx`（GA4 Script ローダー + SPA トラッカー）
- `frontend/src/components/ReportViewTracker.tsx`（サーバーコンポーネント用 GA4 イベント発火）
- `frontend/src/lib/analytics.ts`（GA4 ヘルパー: sendEvent / sendPageView）
- `frontend/src/components/MeguribiHeader.tsx`（グローバルヘッダー）

### Content / Batch
- `scripts/local_report_job.py`（**主経路** — Daily の本体。Ollama `gemma4:e4b` で生成。`experiments/local_llm_spike.py` の `fetch_store_facts`/`run_ollama` を import）
- `scripts/run_weekly_local.ps1`（**主経路** — Weekly のラッパ。`.env.local` 読込 → `generate_weekly_insights.py` 呼び出し）
- `scripts/generate_weekly_insights.py`（`--skip-index` 対応。`--stores all` でローカル実行時に全43店舗を単一プロセス処理。`INSIGHTS_LLM_BACKEND=ollama|gemini`）
- `scripts/tune_local_llm.py`（ローカル LLM 速度チューニング。結果は `local_llm_spike_out/tuning_results.json`）
- `scripts/gpu_lock.py`（音楽プロジェクトと共有する GPU の排他ロック。正本は `C:\Users\Public\共有データ系\gpu_lock.py`、リポジトリ内は復旧用ミラー）
- `scripts/warm_cdn_local.py`（**主経路** — CDN warming。stdlib のみ）
- `scripts/train_ml_model.py`（ML 学習本体。日次は固定パラメータ、週次(月曜)は Optuna HPO）
- `scripts/snapshot_forecasts.py` / `scripts/score_forecasts.py`（v2 shadow の答え合わせ。18:10 snapshot / 06:10 score）
- `scripts/build_templates.py`（v2 shadow のテンプレ再生成。07:30）
- `frontend/scripts/generate-public-facts.mjs`
- `frontend/content/insights/weekly`（JSON + index.json）
- `frontend/content/facts/public`

### Workflows
- `.github/workflows/trigger-blog-cron.yml`（Daily Report。**schedule はコメントアウト済み、`workflow_dispatch`（緊急用）のみ**。matrix max-parallel: 5、オリエンタル38店舗のみ）
- `.github/workflows/generate-weekly-insights.yml`（Weekly Report。**schedule はコメントアウト済み、`workflow_dispatch`（緊急用）のみ**。Fan-in Matrix、オリエンタル38店舗のみ）
- `.github/workflows/train-ml-model.yml`（ML学習。日次05:30 JST(Optunaなし) + 週次月曜07:00 JST(Optuna HPOあり)。これは引き続き GHA が本流）
- `.github/workflows/forecast-accuracy-track.yml`（v2 shadow 答え合わせ。18:10 snapshot / 06:10 score）
- `.github/workflows/build-templates.yml`（v2 shadow テンプレ再生成。07:30 JST）
- `.github/workflows/warm-cdn.yml`（CDN warming バックアップ。プライマリはローカル `MEGRIBI-warm-cdn`）
- `.github/workflows/x-auto-post.yml`（X 自動投稿, workflow_run + dispatch）
- `.github/workflows/generate-public-facts.yml`（Facts 生成, 09:30 JST）
- `.github/workflows/retry-blog-draft-stores.yml`（Daily 失敗再実行, workflow_dispatch）
- `.github/workflows/check-daily-published.yml` / `check-weekly-published.yml`（ローカル生成の公開監視。PCが落ちていても検知可能にする保険）
- `.github/workflows/check-collection-heartbeat.yml`（収集の生存監視）
- `.github/workflows/backup-logs.yml` / `cleanup-old-logs.yml`（Supabase logs のバックアップ・古いログ削除）
- `.github/workflows/blog-ci.yml` / `python-ci.yml`（CI）
- `.github/workflows/check-pat-expiry.yml`（GitHub PAT 期限チェック + LINE 通知, 週次月曜 09:00 JST）
- `.github/workflows/e2e.yml`（Playwright E2E スモークテスト, PR + dispatch）
- `.github/workflows/notify-on-failure.yml`（失敗通知, 再利用ワークフロー）
- `.github/workflows/blog-request.yml`（手動ブログ依頼）
- `.github/workflows/global-ab-experiment.yml`（グローバル A/B 実験用）

### Supabase
- `supabase/migrations/20260326000000_blog_drafts_content_split.sql`
- `supabase/migrations/20260412000000_blog_drafts_indexes.sql`（`updated_at DESC` + `(store_slug, created_at DESC)` インデックス）
