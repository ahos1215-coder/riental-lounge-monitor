# ROADMAP
Last updated: 2026-03-30 (Round 8.5 完了)
Target commit: (see git)

> **構想・フェーズ順・備忘の全文**は **`plan/VISION_AND_FUTURE.md`**。本ファイルは短いタスク一覧と「当面やらないこと」に絞る。

---

## 実装済み（2026-03-26 完了）

### コンテンツ戦略の完全リファクタ（Step 1–5）

| 分類 | URL | 生成 | 公開条件 |
|------|-----|------|---------|
| Daily Report | `/reports/daily/[store_slug]` | GHA 毎日 18:00/21:30 | `is_published=true`（自動） |
| Weekly Report | `/reports/weekly/[store_slug]` | GHA 毎週水曜 06:30 JST | `is_published=true`（自動） |
| Editorial Blog | `/blog/[slug]` | LINE 指示 + Gemini | LINE 承認で `is_published=true` |

**Step 1: DB スキーマ拡張**
- `blog_drafts` に `content_type` / `is_published` / `edition` / `public_slug` を追加
- Migration: `supabase/migrations/20260326000000_blog_drafts_content_split.sql`

**Step 2: 生成パイプライン対応**
- `runBlogDraftPipeline.ts`: `source` から `content_type` / `is_published` を自動導出
- `/api/cron/blog-draft/route.ts`: `content_type='daily'`, `is_published=true` で保存
- `generate_weekly_insights.py`: Supabase upsert（`content_type='weekly'`, `is_published=true`）

**Step 3: ルーティング & UI**
- `/reports/daily/[store_slug]` / `/reports/weekly/[store_slug]` ページ新設
- `/blog/[slug]` は editorial かつ is_published=true のみ表示
- `sitemap.ts` 全店舗分登録

**Step 4: LINE 承認フロー**
- `parseLineIntent.ts`: `approve` / `editorial_analysis` インテント追加
- `blogDrafts.ts`: publish 系関数追加

**Step 5: GitHub Actions Matrix 最適化**
- Daily: `max-parallel: 15`
- Weekly: Fan-in Matrix 構成（Fan-out 38店舗 `max-parallel: 10` → Fan-in で index.json マージ）

### Round 1: パフォーマンス最適化 + セキュリティ + インフラ

| 項目 | 内容 |
|------|------|
| CDN Cache-Control | 全 API proxy に `s-maxage` + `stale-while-revalidate` ヘッダー追加 |
| `/tasks/*` 認証 | `CRON_SECRET` による Bearer 認証追加 |
| 天気 API 429 対策 | Open-Meteo リクエスト間隔拡大 + disk cache（TTL 1時間） |
| cron-job.org 移行 | Daily Report の GHA schedule を削除、外部 cron に完全移行 |
| Facts カード統合 | Daily Report ページに Public Facts サマリカード表示 |

### Round 2: AI予測レポートハブ + megribi_score + ナビゲーション統合

| 項目 | 内容 |
|------|------|
| `/reports` 統合ページ | Daily/Weekly タブ切替・エリアフィルタ・店舗名検索。旧 `/reports/daily` `/reports/weekly` はリダイレクト |
| `/api/megribi_score` | Flask: 全店舗の最新データから megribi_score を算出。Next.js: CDN proxy |
| トップ「今夜のおすすめ」 | megribi_score TOP 5 をカード表示 |
| ヘッダーナビ統合 | 「AI予測」1リンクに集約（ページ内でタブ切替） |
| `/api/reports/list` | 統合一覧ページ用の全店舗最新レポートメタ取得 |

### Round 3: Chart.js 削除 + StoreCard UI 改善

| 項目 | 内容 |
|------|------|
| Chart.js 完全削除 | `chart.js` / `chartjs-adapter-date-fns` / `react-chartjs-2` を package.json から削除。死コード `ForecastNextHourChart.tsx` / `ForecastPreviewChart.tsx` を削除 |
| StoreCard プレースホルダ改善 | `ピーク予測 0人`・`混雑 —`・`狙い目 —` を非表示に。関連店舗カードのラベル二重表記を修正 |

### Round 4: マイページ ダッシュボード化 + X 自動投稿

| 項目 | 内容 |
|------|------|
| マイページ全面リニューアル | お気に入り店舗をリッチカード化（リアルタイム人数・男女スパークライン・megribi_score・ML 予測サマリ・Daily/Weekly リンク）。閲覧履歴をピルタグに圧縮 |
| `/api/sns/post` X API 統合 | OAuth 1.0a 署名・リトライ・dry_run 対応。環境変数未設定時は安全にスキップ |
| `x-auto-post.yml` GHA ワークフロー | `trigger-blog-cron.yml` 完了後に自動実行。許可店舗のみポスト |

### Round 4.5: パフォーマンス最適化（sub-3s ページロード）

| 項目 | 内容 |
|------|------|
| `megribi_score` 並列化 | Flask: ThreadPoolExecutor(12) で 38 店舗並列取得。12s → <1s |
| `range_multi` 並列化 | Flask: ThreadPoolExecutor(12) で Supabase 並列クエリ |
| `forecast_today_multi` 新設 | Flask: 複数店舗の forecast_today を 1 リクエストで返すバッチ API。ThreadPoolExecutor(12) で並列推論 |
| Next.js proxy 追加 | `/api/forecast_today_multi/route.ts` — CDN `s-maxage=60` |
| `/stores` request ordering | 単一 gunicorn worker 対策: ① range_multi await → 部分カード即表示 → ② megribi_score → ③ forecast_today_multi を後続発火。体感 ~1.5s で初期表示 |
| `/store/[id]` 同時発火 | range + forecast を Promise.all で同時発火（従来は直列） |

### Round 5: グロース基盤構築（GA4 計測 + 精度可視化 + UX 改善）

| 項目 | 内容 |
|------|------|
| GA4 導入 | `layout.tsx` に gtag.js 追加。SPA ページ遷移追跡 + カスタムイベント（`store_view`, `report_read`, `favorite_add/remove`）。`NEXT_PUBLIC_GA_MEASUREMENT_ID` で制御 |
| MAE/MAPE 永続化 | `train_ml_model.py` で学習時のメトリクスを `metadata.json` に含める。Flask `/api/forecast_accuracy` + Next.js proxy 追加 |
| ステータス日本語化 | StoreCard の `GO/WAIT/SKIP` → `狙い目/様子見/他店へ` に変更 |
| X 投稿テンプレート改善 | `x-auto-post.yml` に全38店舗の slug→日本語名マッピング追加。ツイート内容を日本語店舗名で表示 |

### Round 6: 品質・信頼性の底上げ（E2E テスト + UX + 統合 + バグ修正）

| 項目 | 内容 |
|------|------|
| デッドコード一括削除 | STATUS.md 記載の未参照ファイル・.bak ファイルを全削除 |
| E2E テスト基盤（Playwright） | 5 テストグループのスモークテスト + CI ワークフロー `e2e.yml` |
| エラーバウンダリ + ローディング UX | 全主要ページに `error.tsx` / `loading.tsx` 11 ファイル追加 |
| Weekly Insights → `/reports/weekly` 統合 | `insight_json` から定量データ（チャート・Good Windows・メトリクス）を Weekly Report ページに統合表示。`/insights/weekly/*` → `/reports/weekly/*` に 301 リダイレクト。`WeeklyStoreCharts.tsx` を共有コンポーネントに移動 |
| GitHub PAT 期限切れ LINE 通知 | 週次 GHA ワークフロー `check-pat-expiry.yml`。30日以内で LINE Push 通知 |
| Daily Report 表示バグ修正 | ① ISR `revalidate` 未設定 → 追加、② データソース不整合（`fetchLatestAutoBlogDraftByStoreSlug` → `fetchLatestPublishedReportByStore`）、③ CDN キャッシュ過長 → 60s に統一 |
| pickPeak 二重カウント修正 | actual + forecast を合算していた → actual 優先フォールバックに変更 |
| ピーク男女別表示改善 | 片方 null でも男女別を表示するように変更 |

### Round 7: ユーザー体験の深化（PWA + OG 画像 + 店舗比較 + Editorial 強化）

| 項目 | 内容 |
|------|------|
| PWA 完成 | アイコン PNG (192/512) 生成 + Service Worker（ネットワークファースト + offline fallback）+ apple-touch-icon 設定 |
| 動的 OG 画像 | `/store/[id]` と `/blog/[slug]` に `opengraph-image.tsx` 追加。全主要ページで動的 OG 画像生成（Edge Runtime） |
| 店舗比較ページ | `/compare` 新設。最大3店舗を並べてリアルタイム混雑を比較（マージチャート・megribi_score・男女別人数カード）。URL state `?stores=a,b,c` |
| ヘッダーナビ拡張 | 「比較」リンクを追加 |
| LINE Editorial 拡張 | 月間まとめ（`月間`/`今月`/`先月`）・エリア比較（同地域店舗の自動選択）スコープ追加。help テキスト更新 |

### Round 8: ML 最適化（評価基盤正常化 + Optuna HPO + Early Stopping）

| 項目 | 内容 |
|------|------|
| Train/Test Split | 時系列順 80%/20% 分割。リーク（Train=Eval）を排除し、Holdout Test で真の汎化精度を報告 |
| 特徴量削減（29→19） | 推論時 NaN になるラグ系 8 列（`men_lag_*`, `women_lag_*`, `men_ma_*`, `women_ma_*`）+ 重複 `dow` + `gender_diff` を `FEATURE_COLUMNS` から除外 |
| Early Stopping | `n_estimators` を 100 固定 → 300 上限 + `early_stopping_rounds=15` で動的決定。店舗ごとに最適な木の数が自動選択 |
| Optuna HPO | 店舗別ハイパーパラメータ最適化（`max_depth`, `learning_rate`, `subsample`, `colsample_bytree`, `min_child_weight`, `reg_alpha`, `reg_lambda`）。デフォルト 30 trials / 店舗 |
| Feature Importance 永続化 | `metadata.json` に店舗別の feature_importance_men / feature_importance_women を記録 |
| schema_version v2 | 特徴量変更に伴い v1→v2 にバンプ。Flask / GHA の両方でデフォルト更新 |

### Round 8.5: SEO 強化 + GA4 有効化 + ML v3 + UX 改善

| 項目 | 内容 |
|------|------|
| SEO: 曜日コンテキスト | Daily Report の `DraftContext` に `day_context`（曜日名・週末フラグ）+ `week_comparison`（同曜日過去ピーク比較）を追加。既存 range データから算出、追加 API コールなし |
| GA4 本番有効化 | GA4 プロパティ作成 → `NEXT_PUBLIC_GA_MEASUREMENT_ID=G-F85T4M53MJ` を Vercel に設定。PV + カスタムイベント計測稼働中 |
| ForecastAccuracyCard | `/store/[id]` と `/reports/weekly/[store_slug]` に予測精度カード追加（MAE / 週末夜 MAE / グレード表示） |
| ML v3: 同曜日先週特徴量 | `same_dow_last_week_total`（7日前同時刻の total）を `FEATURE_COLUMNS` に追加（19→20列）。schema v2→v3 |
| Weekly Insights デフォルト調整 | スクリプトデフォルトを GHA 本番値に統一（threshold 0.80→0.40、min_duration 120→60） |
| UX: エラーメッセージ改善 | 「確認中」→「予測準備中」、予測カード失敗時に説明文表示、「混雑の目安を計算できません」→「予測データ待ち」 |
| updated_at 修正 | `blog_drafts` に `updated_at` カラム + トリガー追加。upsert 時の日時表示バグを修正 |

---

## Round 9（提案: 収益化・拡張）

| # | 項目 | 推奨モデル | 理由 |
|---|------|-----------|------|
| 9-1 | アフィリエイト枠 + UTM 計測 | Sonnet | Daily Report / 店舗詳細に予約リンク枠（**UTM + アフィリエイトリンク基盤実装済み**） |
| 9-2 | 他ブランド対応（JIS・相席屋） | Opus | stores.ts / スクレイパー / UI の大規模拡張設計 |
| 9-3 | Web Push 通知 | Opus | VAPID 鍵・購読管理・送信ジョブの設計 |
| 9-4 | ユーザー認証 + プレミアム機能 | Opus | Supabase Auth / Stripe Checkout の設計判断 |

---

## P0（直近で着手しやすい項目）

- **`avoid_time` / プロンプト**: `draftGenerator.ts` の表現精度向上（ズレる場合は人手修正）
- **主要ドキュメントの継続同期**（`plan/*` と README の整合）
- **Weekly Insights の品質改善**（score 閾値・最小継続時間の調整。`plan/WEEKLY_INSIGHTS_TUNING.md`）
- **`/api/current`**: 当面は Flask 実装維持（`plan/API_CURRENT.md`）

## P1

- Editorial ブログの充実（LINE から定期的に分析記事を作る運用確立）
- 監視・運用の可視化（ログの整理、Render/Vercel 運用の整理）

## P2

- 複数店舗/ブランドの拡張（JIS・相席屋）
- 予測の精度改善（定期学習モデルの評価フレームワーク）
- **PWA / Web Push**
- **OG 画像の動的生成**（予測サマリ入り）
- **店舗比較モード**
- **Stripe・課金・プレミアム予測**（外部助言: 個人開発では当面優先度を下げてよい）

## 当面やらない（方針）

- **PR の URL を LINE に自動送信する**仕組み（**n8n は使わない**）
- `/api/range` へのクエリ追加・サーバ側時間フィルタ
- フロントから Supabase 直アクセス
- 全店舗一斉 X 投稿（段階的に許可店舗を拡大）

## 将来オプション（仕様未定）

- **公開までフル自動**（環境変数 ON/OFF 等）。**ガードレール・Staging 前提**。`VISION_AND_FUTURE.md` §5

## スケール・SEO・Cron（方針の要約）

- **SEO（Daily Report）**: `/reports/daily/[store_slug]` は固定 URL（上書き運用）。カニバリゼーション回避・鮮度優先
- **定時ブログの時計**: **GHA native schedule** が正本（`cron: "0 9 * * *"` JST 18:00、`cron: "30 12 * * *"` JST 21:30）。cron-job.org 不要
- **Weekly の Git コミット**: Fan-in ジョブが 1回のみ commit（競合なし）
- **X 自動投稿**: 開始時は人気トップ5＋長崎店に限定（API・シャドウバンリスク回避）
- **統合レポート一覧**: `/reports` 1 ページに集約。Daily/Weekly はタブで切替（SEO は個別ページで担保）
