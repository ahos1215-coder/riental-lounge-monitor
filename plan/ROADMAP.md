# ROADMAP
Last updated: 2026-03-26 (Round 4 完了)
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

---

## Round 5（提案: 品質・信頼性の底上げ）

| # | 項目 | 推奨モデル | 理由 |
|---|------|-----------|------|
| 5-1 | デッドコード一括削除 | Sonnet | 機械的削除。STATUS.md 記載の未参照ファイル + .bak ファイル |
| 5-2 | E2E テスト基盤 | Sonnet | Playwright 導入、主要3ページ（トップ・店舗一覧・レポート統合）のスモークテスト |
| 5-3 | エラーバウンダリ + ローディング UX | Sonnet | 各ページに `error.tsx` / `loading.tsx` を配置。API エラー時のフォールバック UI |
| 5-4 | Weekly Insights → `/reports/weekly` 統合検討 | Opus | `/insights/weekly` と `/reports/weekly` の重複を整理。データソース統一の設計判断 |
| 5-5 | GitHub PAT 期限切れ LINE 通知 | Sonnet | 週次 GHA ワークフロー + LINE Push API |

## Round 6（提案: ユーザー体験の深化）

| # | 項目 | 推奨モデル | 理由 |
|---|------|-----------|------|
| 6-1 | PWA 対応（Web App Manifest + Service Worker） | Sonnet | オフライン対応・ホーム画面追加 |
| 6-2 | OG 画像の動的生成 | Sonnet | `/reports/daily/[store_slug]` の OG 画像にその日の予測サマリを含める |
| 6-3 | 店舗詳細ページの「比較モード」 | Opus | 2-3 店舗を並べて比較するレイアウト設計が必要 |
| 6-4 | Editorial ブログの運用フロー強化 | Opus | LINE から「月間まとめ」「エリア比較」等の複雑な分析依頼に対応 |

## Round 7（提案: 収益化・拡張）

| # | 項目 | 推奨モデル | 理由 |
|---|------|-----------|------|
| 7-1 | アフィリエイト枠 + UTM 計測 | Sonnet | Daily Report / 店舗詳細に予約リンク枠 |
| 7-2 | 他ブランド対応（JIS・相席屋） | Opus | stores.ts / スクレイパー / UI の大規模拡張設計 |
| 7-3 | Web Push 通知 | Opus | VAPID 鍵・購読管理・送信ジョブの設計 |
| 7-4 | ユーザー認証 + プレミアム機能 | Opus | Supabase Auth / Stripe Checkout の設計判断 |

---

## P0（直近で着手しやすい項目）

- **デッドコード削除**: STATUS.md に記載の未参照ファイル・.bak ファイルのクリーンアップ
- **`avoid_time` / プロンプト**: `draftGenerator.ts` の表現精度向上（ズレる場合は人手修正）
- **主要ドキュメントの継続同期**（`plan/*` と README の整合）
- **Weekly Insights の品質改善**（score 閾値・最小継続時間の調整。`plan/WEEKLY_INSIGHTS_TUNING.md`）
- **`/api/current`**: 当面は Flask 実装維持（`plan/API_CURRENT.md`）

## P1

- **E2E テスト**: Playwright による主要ページのスモークテスト
- **エラー UX**: `error.tsx` / `loading.tsx` の充実化
- Editorial ブログの充実（LINE から定期的に分析記事を作る運用確立）
- **GitHub PAT 期限切れ通知**（LINE Push API で週次チェック）
- 監視・運用の可視化（ログの整理、Render/Vercel 運用の整理）
- **`/insights/weekly` と `/reports/weekly` の重複整理**

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
- **定時ブログの時計**: **cron-job.org** が正本（JST 18:00 / 21:30）。GHA schedule なし
- **Weekly の Git コミット**: Fan-in ジョブが 1回のみ commit（競合なし）
- **X 自動投稿**: 開始時は人気トップ5＋長崎店に限定（API・シャドウバンリスク回避）
- **統合レポート一覧**: `/reports` 1 ページに集約。Daily/Weekly はタブで切替（SEO は個別ページで担保）
