# STATUS
Last updated: 2026-05-04 (Round 12: Weekly Report v2 redesign — heatmap + 日別サマリ + AI 自然文解説 (先週/来週) + 来週の狙い目 + 賑わいスコアバー削除)
Target commit: (see git)

## 現在動いている機能

### Backend (Flask / Render Starter $7/月, 2025-12〜)
- `/healthz`（稼働確認）
- `/api/current`（ローカル保存の最新レコード。Supabase 直取得ではない）
- `/api/range`（**`store` / `limit` のみ**。Supabase は `ts.desc` 取得 → 返却は `ts.asc`、**サーバ側の夜窓フィルタなし**）
- `/api/range_multi`（**`stores=slug1,slug2,...` + `limit` 等**。Supabase のみ。店舗一覧の一括 range 取得用。**ThreadPoolExecutor(12) で並列取得**）
- `/api/meta`（設定サマリ）
- `/api/forecast_today` / `/api/forecast_next_hour`（`ENABLE_FORECAST=1` のときのみ。無効時は 503）
  - **店舗別最適化モデル（ML 3.0）本番稼働中**。全38店舗で Optuna HPO + Early Stopping による個別最適化モデル。
  - **LightGBM 移行完了 (2026-04-12〜)**: 推論メモリを XGBoost の約半分に削減。モデルファイル 179KB → 97KB (46% 削減)。学習時間も 30-40分 → 5分11秒に短縮。`model_xgb.py` は LightGBM を優先ロード、XGBoost フォールバック保持。
  - `model_registry.py` は `metadata.json` の `has_store_models` / `store_models` を検証し、**店舗別モデルを最優先でロード**。不整合時は明示エラー、未対応メタデータ時のみグローバルモデルへフォールバック。
  - **schema_version v6 (2026-05-03〜)**: 特徴量 24 列。v5 の 22 + `holiday_block_length` / `holiday_block_position` (連休クラスタ判定 — `oriental/ml/holiday_calendar.py`)。GW・お盆・年末年始など連続休業期間を検出し、連休内位置 (初日/中日/最終日) を ML に伝える。お盆 8/13-15・年末年始 12/29-1/3 を慣習的休業日として扱う
  - **schema_version v5 (2026-04-13〜)**: 特徴量 22 列。v4 の 21 + `extreme_weather`（猛暑 35°C+ / 極寒 5°C- の極端天候フラグ）
  - **時間減衰ウェイト**: 学習時のサンプル重み付けに指数減衰（90日半減期）を追加。直近データを重視
  - **日次精度トラッキング**: `metadata.json` に店舗別・日別の MAE を自動記録
  - **Flask プロセス内キャッシュ**: TTL 60s（`FORECAST_RESULT_CACHE_TTL`）。CDN キャッシュと合わせ最大遅延 ~2 分
  - **Disk cache fallback (2026-04-12〜)**: `model_registry.py` は Supabase Storage からの DL が `download_retry` 回失敗しても、`forecast_model_cache_dir` 上の既存ファイルが `FORECAST_MODEL_CACHE_MAX_AGE_SEC`（既定 7 日）以内なら fallback として採用。さらに、TTL 切れの refresh 中に DL が失敗した場合はメモリ内の前回バンドルを継続使用（`refresh_failed_using_stale_in_memory` 警告）。一過性の Supabase Storage 接続リセット（`Connection reset by peer`）で予測 API が止まるのを防ぐ
- `/api/forecast_today_multi`（`?stores=slug1,slug2,...` 最大40店舗。**ThreadPoolExecutor(12) で並列実行** — 12店舗でも ~1-2s。Flask 内キャッシュ共有）
- `/api/second_venues`（最小応答。未設定時は空配列）
- `/api/megribi_score`（全店舗 or 指定店舗の megribi_score を返す。`?store=` / `?stores=` 対応。Supabase backend 必須。**ThreadPoolExecutor(12) で並列取得 — 38店舗12s→<1s**）
- `/api/forecast_accuracy`（`metadata.json` から店舗別 MAE/RMSE メトリクスを返却。**Holdout Test（直近20%）による真の汎化精度**。Feature importance も含む）
- `/api/holiday_status`（**2026-05-03〜**。任意の日付について連休判定を返す。`?date=YYYY-MM-DD` 省略時は JST 今日。返却: `block_length` (連続休業日数 0-9) / `block_position` (0.0=初日 1.0=最終日 / 平日は 0.5) / `is_long_holiday` (block_length>=4) / `label` (例: "5連休 (3/5日目)")。実装: `oriental/ml/holiday_calendar.py` の `get_holiday_block` / `is_long_holiday`。フロントの `LongHolidayBanner` が消費）
- `/tasks/multi_collect` / `/api/tasks/collect_all_once`（本番収集の入口 → Supabase `logs`。デフォルト 202 Accepted + バックグラウンドスレッド実行。`?mode=sync` で旧同期モード。`/tasks/multi_collect/status` でステータス確認）
  - **Phase 2 (Oriental Lounge)**: トップページ一括取得 (1 リクエストで 38 店舗、`src_brand="oriental"`)
  - **Phase 2b (相席屋)**: トップページから 6 店舗のパーセンテージを抽出 → 座席数 × % で逆算 (`src_brand="aisekiya"`、2026-04-17〜)
  - 1 サイクル合計 1+1=2 リクエストで全 44 店舗のデータを収集
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
| `/store/[id]` | 店舗詳細（リアルタイムカード・Recharts 時系列・ML 予測・**LongHolidayBanner** (連休期間中のみ)・「今日の傾向まとめ」・**Weekly Report 要約カード**・関連店舗・**range + forecast 同時発火**）。Daily Report 専用カードは `/store/[id]` から削除済み (2026-04-23) |
| `/reports` | **AI予測レポート統合一覧**（Daily/Weekly タブ切替・エリアフィルタ・店舗名検索。ヘッダー「AI予測」からリンク） |
| `/reports/daily` | `/reports` へリダイレクト |
| `/reports/daily/[store_slug]` | **Daily Report 個別**: 最新 `content_type='daily'`・`is_published=true`。Facts カード表示 |
| `/reports/weekly` | `/reports?tab=weekly` へリダイレクト |
| `/reports/weekly/[store_slug]` | **Weekly Report 個別**: 最新 `content_type='weekly'`・`is_published=true`。**v2 redesign (2026-05〜)**: 先週の日別サマリ → AI 観測「先週の傾向」(Markdown 箇条書き) → 今週の分析メトリクス → ヒートマップ (時間×曜日) → AI 予想「来週の予想傾向」(Markdown 箇条書き) → 来週の狙い目時間 TOP 3 → 賑わいやすい時間帯 → 予測モデル精度。各セクションは insight_json のフィールドが無いと安全に隠す |
| `/blog` | 編集ブログ一覧。AI予測レポート一覧への誘導バナー付き |
| `/blog/[slug]` | **editorial（`content_type='editorial'`, `is_published=true`）のみ**表示 |
| `/insights/weekly` | **→ `/reports?tab=weekly` に 301 リダイレクト**（統合済み） |
| `/insights/weekly/[store]` | **→ `/reports/weekly/[store]` に 301 リダイレクト**（統合済み。旧ページは残存するがリダイレクトが優先） |
| `/compare` | **店舗比較**: 最大3店舗を並べてリアルタイム混雑を比較。マージチャート（実測+予測）・megribi_score・男女別人数カード。URL パラメータ `?stores=a,b,c` で状態共有 |
| `/mypage` | **ダッシュボード型マイページ**: お気に入り店舗リッチカード（リアルタイム人数・男女スパークライン・megribi_score・ML 予測サマリ・Daily/Weekly リンク）+ 閲覧履歴ピルタグ |

#### Next.js API Routes（15本）
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
| `/api/forecast_accuracy` | Flask `/api/forecast_accuracy` プロキシ（CDN `s-maxage=3600`） |
| `/api/holiday_status` | Flask `/api/holiday_status` プロキシ（CDN `s-maxage=3600` — 連休判定は日付固定なので長めにキャッシュ） |
| `/api/sns/post` | X (Twitter) 投稿 API（OAuth 1.0a・dry_run 対応） |

#### GA4 アナリティクス
- **Google Analytics 4**: `NEXT_PUBLIC_GA_MEASUREMENT_ID=G-F85T4M53MJ` で **本番有効化済み**（2026-03-29）
- `next/script` の `afterInteractive` 戦略で gtag.js を非同期ロード
- SPA ページ遷移追跡: `usePathname` + `useSearchParams` で `sendPageView` を自動発火
- カスタムイベント: `store_view`（店舗詳細）、`report_read`（Daily/Weekly）、`favorite_add` / `favorite_remove`（お気に入り操作）
- ヘルパー: `frontend/src/lib/analytics.ts`（`sendEvent` / `sendPageView`）
- コンポーネント: `GoogleAnalytics.tsx`（Script ローダー + SPA トラッカー）、`ReportViewTracker.tsx`（サーバーコンポーネント用クライアントラッパー）

#### その他フロントエンド機能
- **LINE Webhook（本番パス）**
  - `POST /api/line`: 署名検証 → **レート制限**（Upstash。グローバル/分＋ユーザーあたり下書き/時。**Upstash 障害時は in-memory フォールバック + 5 分の circuit breaker** で webhook を継続稼働 — 2026-04-12〜）→ テキスト解析 → 3 インテント:
    - **`draft` / `editorial_analysis`**: Flask `/api/range` + `/api/forecast_today` → `insightFromRange.ts` → Gemini MDX → Supabase `blog_drafts`（`content_type='editorial'`, `is_published=false`）
    - **`approve`**: 最新の未公開 editorial を `is_published=true` に更新 → `/blog/[public_slug]` URL を返信
- **OGP / メタデータ**: `metadataBase`、動的 OG 画像、全ページの `openGraph` / `twitter` 設定済み。canonical は **`https://www.meguribi.jp`** に統一（2026-04-19〜。`meguribi.jp` → 307 リダイレクト）
- **Sitemap**: `/reports`（統合一覧）+ `/reports/daily/[store_slug]`（priority 0.85 / daily）+ `/reports/weekly/[store_slug]`（priority 0.8 / weekly）全店舗分。旧 `/blog/auto-*` は廃止。**Google Search Console 登録済み (2026-04-19)**: 145 ページ検出成功
- **robots.txt** (`frontend/src/app/robots.ts`, 2026-04-19〜): `/api/` と `/mypage` を Disallow、`Sitemap:` 行で sitemap.xml の場所を明示
- **Recharts**: 全チャートを Chart.js → Recharts に統一済み（Round 3）。Chart.js 依存は完全削除
- **StoreCard**: データ未取得時のプレースホルダ（`—`・`0人`）を非表示化（Round 3）。めぐりびスコアバッジ: `狙い目`（≥0.65）/ `様子見`（≥0.40）/ `他店へ`（<0.40）
- **ForecastAccuracyCard**: `/store/[id]` ページに予測モデル精度カード表示（MAE / 週末夜 MAE / グレード表示）。`/api/forecast_accuracy` からクライアントサイドでフェッチ（モジュールレベルキャッシュ）
- **LongHolidayBanner (2026-05-03〜)**: `/store/[id]` ページの `PreviewMainSection` 内、タイムライングラフと「今日の傾向まとめ」の間に表示。`/api/holiday_status` を呼び `is_long_holiday=true` (連続休業 4 日以上) のときのみバナー表示。文言: 「連休中は普段と異なる人の流れが起きるため、予測との乖離が大きくなる傾向があります」。GW・お盆・年末年始など ML が未学習の期間で予測がズレやすい点を読者に明示する目的 (`frontend/src/components/store/LongHolidayBanner.tsx`)
- **WeeklyHeatmap (2026-05-03〜)**: `/reports/weekly/[store]` の中核チャート。10 行 (時間帯) × 7 列 (曜日) のグリッド、混雑度をデータセット内最大値で正規化 + ガンマ補正 + 多色グラデ (青→紫→桃赤) で表現。ホバー時に曜日 / 時間帯 / 混雑度 % / 女性比 % / サンプル数を詳細表示 (`frontend/src/components/WeeklyHeatmap.tsx`)
- **WeeklySummary (2026-05-03〜)**: `/reports/weekly/[store]` の先頭近くに表示する 7 日分の日別サマリ。各「夜」(19:00-翌04:59) の avg/peak 混雑度をバーで一覧、一番賑わった夜を強調 (`frontend/src/components/WeeklySummary.tsx`)
- **予測自動再試行 UX (2026-04-12〜)**: `useStorePreviewData.ts` は `/api/forecast_today` が空配列を返した場合（ML モデル一過性ロード失敗の典型症状）、5s → 15s → 45s のバックオフで最大 3 回自動再試行する。`StoreSnapshot.forecastStatus` に `idle` / `ok` / `retrying` / `unavailable` を出力し、`PreviewMainSection.tsx` が「予測データを再取得しています…」「予測データを取得できませんでした。実測グラフのみ表示しています。」のヒントを表示
- **ブログ frontmatter**: Zod 検証（`blogFrontmatter.ts` / `content.ts`）
- **CDN Cache-Control**: API proxy に `s-maxage` + `stale-while-revalidate` 設定。予測系（`forecast_today` / `forecast_next_hour`）は `s-maxage=60`（Flask TTL も 60s）、最大遅延 ~2 分
- **エラーバウンダリ + ローディング UX**: 全主要ページに `error.tsx`（リトライボタン + 一覧戻りリンク）/ `loading.tsx`（パルスアニメーション骨格）を配置。`store/[id]`, `mypage`, `reports/daily/[store_slug]`, `reports/weekly/[store_slug]`, `blog`, `blog/[slug]`, `insights/weekly` の 11 ファイル
- **E2E テスト基盤**: Playwright 導入。9 テストグループ（トップ・店舗一覧・店舗詳細・レポート統合・比較・マイページ・ブログ・ナビゲーション・エラー処理）のスモークテスト。CI ワークフロー `e2e.yml`
- **公開 API レート制限**: 全 proxy API route に IP ベースのスライディングウィンドウ制限（デフォルト 60 req/min、batch 系は 20-30 req/min）。`apiRateLimit.ts`
- **ML モデルプリロード**: Flask 起動時にバックグラウンドスレッドで全 38 店舗のモデルをメモリに先読み。初回リクエストの 5s/店舗 の遅延を解消
- **Recharts 遅延読み込み**: `next/dynamic` で PreviewMainSection / CompareClient を lazy load。初期バンドル ~200KB 削減
- **Supabase 容量管理**: `cleanup-old-logs.yml`（週次 cron）。1年超データのダウンサンプリング + 300万行上限の緊急削除。Free Tier 500MB を超えない安全弁
- **SHAP 分析スクリプト**: `scripts/shap_analysis.py` — 店舗別の特徴量寄与度を SHAP TreeExplainer で診断
- **UI 強化**: lucide-react アイコン、framer-motion フェードインアニメーション、モバイルハンバーガーメニュー、アクティブページハイライト
- **GitHub PAT 期限切れ監視**: 週次 GHA ワークフロー `check-pat-expiry.yml`。GitHub API でトークン有効期限を取得し、30日以内なら LINE Push で通知（7日以内は赤アラート）
- **PWA**: Web App Manifest + アイコン PNG (192/512) + Service Worker（ネットワークファースト + stale-while-revalidate）。ホーム画面追加・オフラインフォールバック対応
- **動的 OG 画像**: `opengraph-image.tsx` を全主要ページに配置（ルート・Daily Report・Weekly Report・店舗詳細・ブログ記事）。Edge Runtime で動的生成
- **LINE Editorial 拡張**: 月間まとめ（`月間`/`今月`/`先月`）・エリア比較（同地域店舗の自動選択）スコープ対応。topicHint にスコープ情報を埋め込み Gemini に渡す

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
- **構成**: 38店舗 × 独立 matrix ジョブ、**`max-parallel: 5`** (`989637e`, 2026-04 — Gemini 無料枠の RPM 制限に合わせて 15 → 5 に削減済)、`continue-on-error: true`
- **エンドポイント**: `GET /api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
- **保存**: Supabase `blog_drafts`（`content_type='daily'`, `is_published=true`）
- 失敗店舗のみ再実行: `retry-blog-draft-stores.yml`
- 部分失敗通知: `summarize-blog-matrix` → `notify-partial-blog-failures`（`OPS_NOTIFY_WEBHOOK_URL` 設定時）
- **X 自動投稿**: Daily Report 生成後、`x-auto-post.yml` が `workflow_run` で自動トリガー。許可店舗のみ投稿
- **プロンプト v2 (Phase 1, 2026-04-19〜、`plan/BLOG_REDESIGN_2026_04.md`)**: 旧「禁止事項羅列」→ 新「観測者ペルソナ + 型 + 良い例/避ける例」。`buildSystemInstruction()` (`frontend/src/lib/blog/draftGenerator.ts`):
  - ペルソナ「夜遊びに詳しい友人がデータを見ながらつぶやく」距離感
  - 構造強制を撤廃 (旧「## 今日の結論 + 箇条書き 3-4 行」固定 → 新「自然文 100-200字、箇条書き / 見出し禁止」)
  - 予測は断定回避 (「21時にピークが来ます」❌ → 「21時あたりが山になりそう」✅)
  - **2 エディションは独立**: `late_update` (21:30) は `evening_preview` (18:00) の予測には言及しない (予測精度の露呈防止)
  - Few-shot: 良い例 / 避ける例を system prompt 末尾に固定埋め込み
  - 後段の `buildFallbackBlogDraftMdx()` は依然旧スタイル (Phase 4 で書き換え予定 — `plan/BLOG_REDESIGN_2026_04.md`)
- **指示文漏洩修正 (2026-04-23, `fd9a195`)**: `secondary_wave.note` / `gender_note` から AI 指示語 (「控えめに言及してよい (断定禁止)」「過度に楽観・悲観しない説明にしてください」) を除去。AI が本文に書き写してユーザーに見えていたバグ
- **/store/[id] からの Daily Report カード削除 (2026-04-23, `fd9a195`)**: 同ページの「今日の傾向まとめ」(`LatestForecastSummaryCard`) と内容重複のため削除。Weekly Report カードは残置

#### Weekly Report（`content_type='weekly'`, `is_published=true`）
- **Workflow**: `.github/workflows/generate-weekly-insights.yml`（毎週水曜 06:30 JST = UTC 火曜 21:30）
- **構成（Fan-in Matrix）**:
  - **Fan-out** `generate-store`: 38 店舗 × 独立ジョブ、`max-parallel: 10`。`--skip-index` で `index.json` 更新を抑制。Supabase upsert は各ジョブ内で完結
  - **Fan-in** `collect-and-commit`: 全 Artifact を回収 → `index.json` マージ再構築 → Git commit 1回
- **出力先**: `frontend/content/insights/weekly/<store>/<date>.json` + `index.json`
- **v2 redesign (2026-05-03〜、`plan/WEEKLY_REPORT_REDESIGN_2026_05.md`)**:
  - **Phase A — `metric_interpretations`**: 既存メトリクスに「だから何?」のラベルを添える (例: "1 日平均 142 件・平常", "中規模店レベル")
  - **Phase B — `day_hour_heatmap`**: 7 曜日 × 10 時間 (19-04時) のヒートマップ。**0-4時のデータは前日の夜セッションとして集計** (例: 日曜 00:00 → 土曜行)。フロント `WeeklyHeatmap.tsx` が消費。多色グラデ (青→紫→桃赤、最大値正規化、ガンマ補正) で混雑度の差を強調。**軸は時間 (Y) × 曜日 (X)** (横方向に 1 時間を週全体でスキャンするため)
  - **Phase C — `last_week_summary` / `next_week_forecast`**: Gemini 2.5 Flash による自然文解説 2 セクション。`INSIGHTS_GENERATE_AI_COMMENTARY=1` + `GEMINI_API_KEY` 設定時のみ動作。**responseSchema** で構造化出力を強制、**maxOutputTokens=2000** で切断防止、**正規表現フォールバックパーサ**で JSON 破損を救出、**429 リトライ (5s/15s/45s) + gemini-2.5-flash-lite フォールバック**、**生成失敗時は既存レコードの文章を保持** (上書き消失防止)。出力は **です・ます調 + Markdown 箇条書き必須** (リード文 1 行 + 3-5 項目)
  - **Phase D — `next_week_recommendations`**: ヒートマップ上位 3 セル (`sample_count>=2`) を「来週の狙い目時間 TOP 3」として派生。`day_label_ja` / `hour_label` / `avg_occupancy` / `avg_female_ratio` を含む
  - **`daily_summary`**: 直近 7 夜分の日別サマリ (各夜 19:00-翌04:59 を 1 単位、avg/peak occupancy + female_ratio + sample_count)。一番賑わった夜を強調
  - **削除**: 旧「1 週間の混雑推移」折れ線グラフ (時系列で曜日パターンが読めなかった) + 旧「賑わいスコア」バーチャート (機能重複・直感性ゼロ)
  - **既存データの後方互換**: 旧 JSON は `daily_summary` / `day_hour_heatmap` / AI フィールドが無いが、フロントは各セクションを条件付きレンダリングで安全に隠す。次回 cron 実行で全店舗 v2 化される

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
| `train-ml-model.yml` | ML モデル学習 + Supabase Storage | `schedule`（**日次** UTC 20:30 = JST 05:30 Optuna なし + **週次** 日曜 UTC 22:00 = JST 月曜 07:00 Optuna あり）+ dispatch |
| `x-auto-post.yml` | X 自動投稿 | `workflow_run`（Daily 完了後）+ dispatch |
| `retry-blog-draft-stores.yml` | Daily 失敗店舗再実行 | `workflow_dispatch` |
| `blog-request.yml` | 手動ブログ依頼 | `workflow_dispatch` |
| `blog-ci.yml` | フロント CI（type-check / build） | push |
| `check-pat-expiry.yml` | GitHub PAT 有効期限チェック + LINE 通知 | `schedule`（月曜 09:00 JST）+ dispatch |
| `e2e.yml` | Playwright E2E スモークテスト | `pull_request` + dispatch |
| `cleanup-old-logs.yml` | Supabase logs 容量管理（ダウンサンプリング + 緊急削除） | `schedule`（月曜 07:00 JST）+ dispatch |
| `notify-on-failure.yml` | 失敗通知（再利用） | `workflow_call` |

### LINE 下書きパイプライン（要点）
- **n8n は使わない（廃止）**。司令塔は Next.js のみ
- インサイト: `frontend/src/lib/blog/insightFromRange.ts`（今夜窓 → 全日フォールバック）。**曜日コンテキスト（`day_context`）+ 同曜日過去比較（`week_comparison`）** を `DraftContext` に追加済み（SEO 差別化用。既存 range データから算出、追加 API コール不要）
- 下書き生成: `frontend/src/lib/blog/draftGenerator.ts`（既定 Gemini モデルは **`gemini-2.5-flash`**）
- 意図解析: `frontend/src/lib/line/parseLineIntent.ts`（`draft` / `editorial_analysis` / `approve`）

### Cron 構成（外部トリガー）

| サービス | 対象 | JST | 備考 |
|----------|------|-----|------|
| GHA schedule | `trigger-blog-cron.yml` | 18:00 / 21:30 | UTC 09:00 / 12:30。cron-job.org 不要 |
| cron-job.org | `/tasks/multi_collect` | 5分毎（営業時間帯） | `CRON_SECRET` 認証 |
| GHA schedule | `train-ml-model.yml` | 05:30 | UTC 20:30 |
| GHA schedule | `generate-public-facts.yml` | 09:30 | UTC 00:30 |
| GHA schedule | `generate-weekly-insights.yml` | 水曜 06:30 | UTC 火曜 21:30。`INSIGHTS_GENERATE_AI_COMMENTARY=1` + `GEMINI_API_KEY` で AI 自然文解説 (last_week_summary / next_week_forecast) を生成 |

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
- **Supabase Free Tier (500MB) のストレージ**: 5分間隔 × 38店舗 × 営業時間帯 = ~4,560行/日、~166万行/年。1行 ~300-500 bytes + index で推定 500-800MB/年。**1年前後で DB 容量の監視が必要**。必要に応じて過去ログのダウンサンプリング（5分→1時間）または Supabase Pro への移行を検討
- Daily Report は `/api/cron/blog-draft` の 1リクエスト完了時間が Vercel の制約（~60秒）に近い場合がある。504 再発時は `plan/BLOG_CRON_ASYNC_FUTURE.md`
- Open-Meteo 天気 API は 429 レート制限あり。リクエスト間隔を十分空けること（天気データは disk cache + TTL で 1 時間に 1 回取得）

## 識別済みデッドコード
- ✅ **全て削除済み**（Round 6-1, 2026-03-28 確認）: PreviewHeader, HomeHeroSection, DashboardPreview, DebugPanel/DebugSection, types/range, forecast_common, blog/_data, .bak ファイル群
