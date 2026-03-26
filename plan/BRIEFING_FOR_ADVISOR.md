# 相談役（Gemini 等）向けブリーフィング
Last updated: 2026-03-26

以下をそのまま（または要約して）外部の AI に貼り付け、**より良い案・優先順位・リスク**についてアドバイスを求める用途向けです。  
リポジトリ内の正本は `plan/*.md` です。

---

## 1. プロジェクト概要

- **名前**: MEGRIBI（めぐりび）/ Oriental Lounge Monitor（リポジトリ名）
- **目的**: 相席ラウンジ等の **混雑状況の可視化** と（設定により）**簡易予測** を通じて、来店タイミングの判断材料を提供する **Web サービス**。
- **開発形態**: **個人開発**（本番運用・収益化の志向はあるが、技術ドキュメント上は必須要件としては書いていない）。
- **データの正本**: **Supabase `logs`**（Google Sheet / GAS はレガシー fallback）。

---

## 2. 技術スタック

| 層 | 技術 |
|----|------|
| DB / バックエンドデータ | Supabase |
| API | **Flask**（Render 上を想定） |
| フロント | **Next.js**（App Router、**Vercel**） |
| 収集 | Python（`multi_collect` 等）、`/tasks/multi_collect` が Supabase へ書き込み |
| バッチ | **GitHub Actions**（Daily Report・Weekly Report → Supabase + ファイルにコミット） |
| コンテンツ生成 | Vercel の **`POST /api/line`** または **GHA** → Flask `/api/range` → インサイト → **Gemini** → Supabase `blog_drafts` |
| 予測 | Flask の `/api/forecast_*`（`ENABLE_FORECAST=1` のとき）。**XGBoost** 系は `oriental/ml/` |

---

## 3. 現状（2026-03-26 時点）— 何が動いているか

### 3a. Web ページ（実装済み）

| パス | 内容 |
|------|------|
| `/` | トップ。StoreCard＋ブログ新着＋Daily Report 誘導 |
| `/stores` | 全店舗一覧（38店舗、地域タブ・ページネーション） |
| `/store/[id]` | 店舗詳細（リアルタイム混雑・男女比・予測） |
| **`/reports/daily/[store_slug]`** | **Daily Report**（毎日 18:00/21:30 に自動更新される最新AI予測。全38店舗）|
| **`/reports/weekly/[store_slug]`** | **Weekly Report**（毎週水曜 06:30 JST 更新のAI週報。全38店舗）|
| `/insights/weekly/[store]` | Recharts 可視化（Good Window 時系列）|
| `/blog` | Editorial ブログ一覧（AI予測レポートへの誘導バナー付き） |
| **`/blog/[slug]`** | **Editorial Blog**（LINE 指示 → AI下書き → 人間承認後のみ表示） |
| `/mypage` | お気に入り・閲覧履歴（localStorage） |

### 3b. コンテンツの 3 分類（今回の最大変更点）

2026-03-26 に「ブログ」を 3 種類に明確分離し、Supabase スキーマ・生成パイプライン・URL・GHA ワークフロー・フロントエンドをすべて実装済み。

| 種類 | `content_type` | URL | 生成元 | `is_published` |
|------|----------------|-----|--------|----------------|
| AI 予測予報 | `daily` | `/reports/daily/[store_slug]` | GHA 毎日 18:00/21:30 | 自動 `true` |
| AI 週報 | `weekly` | `/reports/weekly/[store_slug]` | GHA 毎週水曜 06:30 JST | 自動 `true` |
| 編集ブログ | `editorial` | `/blog/[public_slug]` | LINE 指示 + Gemini | LINE 承認後 `true` |

### 3c. GitHub Actions ワークフロー（実装済み）

**Daily Report**（`trigger-blog-cron.yml`）:
- 38 店舗 × 独立ジョブ（`max-parallel: 15`）
- `GET /api/cron/blog-draft?store=<slug>&edition=<edition>`
- Supabase に `content_type='daily'`, `is_published=true` で保存
- 失敗店舗は `retry-blog-draft-stores.yml` で再実行可能

**Weekly Report**（`generate-weekly-insights.yml`）— **Fan-in Matrix 構成**:
- **Fan-out**: 38 店舗 × 独立ジョブ（`max-parallel: 10`）。各ジョブが `generate_weekly_insights.py --skip-index` 実行 → Supabase upsert → Artifact 保存
- **Fan-in**: 全 Artifact を回収 → `index.json` をマージ再構築 → Git commit 1回

### 3d. Supabase `blog_drafts` スキーマ（2026-03-26 拡張）

```sql
-- 追加カラム（Migration 済み）
content_type  TEXT  CHECK ('daily','weekly','editorial')
is_published  BOOLEAN DEFAULT false
edition       TEXT   -- 'evening_preview','late_update','weekly'
public_slug   TEXT   -- /blog/[slug] に使用（UNIQUE where not null）

-- インデックス
facts_id UNIQUE
public_slug UNIQUE (where not null)
(content_type, is_published, store_slug, created_at DESC)
```

### 3e. LINE Webhook の 3 インテント（実装済み）

1. **`draft` / `editorial_analysis`**: 「○○を分析して」→ Gemini 下書き → Supabase（`is_published=false`）
2. **`approve`**: 「公開」「ok」→ `is_published=true` → `/blog/[slug]` URL を返信
3. **その他**: help テキストを返信

---

## 4. 不変の方針・制約

- `/api/range` に **from/to 等のクエリ追加やサーバ側夜窓フィルタ**を入れない（契約固定）
- フロントから **Supabase を直接叩かない**（サーバー側のみ）
- 二次会スポットは **map-link（検索リンク）** が本流（Places API 前提に戻さない）
- ブログ／LINE 配管に **n8n は使わない**
- **PR の URL を LINE に自動送信**は **当面やらない**
- `blog_drafts` の `content_type` は `daily` / `weekly` / `editorial` の 3種類のみ
- `daily` / `weekly` は人間の承認不要で自動公開。`editorial` のみ LINE 承認必須

---

## 5. 今後の方針（フェーズ）

### フェーズ A — 今〜短期（運用安定・コンテンツ拡充）
- Daily/Weekly Report の運用安定確認（Supabase に正しく保存されているか）
- Editorial ブログの実際の使い方確立（LINE で定期的に分析記事をオーダーする習慣）
- `/reports/daily/` / `/reports/weekly/` の UX 改善（ナビゲーション・一覧ページ等）
- Weekly Insights パラメータ調整（`INSIGHTS_THRESHOLD` / `INSIGHTS_MIN_DURATION_MINUTES`）
- `LINE_RANGE_LIMIT` / `BLOG_CRON_RANGE_LIMIT` の運用調整（既定 500）

### フェーズ B — X（Twitter）発信
- 投稿 API ルート（`/api/sns/post`）スケルトン実装済み
- Daily Report の URL を毎日 X に投稿（最初は人気5店舗＋長崎店に限定）

### フェーズ C — 予測・ML 精度向上
- オフライン評価、本番方針（オンザフライ学習 vs 定期学習モデル配布）の決定

### フェーズ D — PWA・通知
### フェーズ E — 課金・プレミアム

---

## 6. SEO 戦略

- **Daily/Weekly**: 固定 URL（`/reports/daily/[store_slug]`・`/reports/weekly/[store_slug]`）で上書き運用。Freshness を優先。旧 `/blog/auto-*` URL は廃止済み。
- **Editorial**: `/blog/[public_slug]` でユニーク URL。深い分析記事でロングテール狙い。
- `sitemap.ts` に Daily（priority 0.85, daily）+ Weekly（priority 0.8, weekly）を全38店舗分登録済み。

---

## 7. 現在の課題・相談したいこと

1. **Daily/Weekly Report の表示 UI**: 現状はシンプルな Markdown 表示。グラフ・予測結果の視覚化をどこまでやるか。
2. **Editorial ブログの運用定着**: LINE でどれくらいの頻度・内容でオーダーするか。記事テーマの具体例・テンプレ。
3. **`/reports/daily/` の一覧ページ**: 現状は各店舗の直接 URL のみ。全店舗のレポートリストページは必要か。
4. **Weekly Report と Weekly Insights の役割重複**: `/insights/weekly/[store]`（Recharts）と `/reports/weekly/[store_slug]`（Markdown）が並存している。統合すべきか。
5. **X（Twitter）投稿の開始タイミング**: Daily Report の URL を毎日投稿する自動化をいつ始めるか。
6. **アーカイブの必要性**: Supabase には過去の daily/weekly が全て残るが、公開 URL は最新1件のみ。過去分へのアクセスをどう扱うか（SEO 的に意味があるか）。

---

## 8. Gemini に一緒にアップロードするとよいファイル（優先度順）

1. **`plan/STATUS.md`** — 現状の機能一覧（事実の正）
2. **`plan/ARCHITECTURE.md`** — データフロー・ファイル構成
3. **`plan/BLOG_PIPELINE.md`** — 3種類のコンテンツ生成フロー詳細
4. **`plan/DECISIONS.md`** — 変更してはいけない判断
5. **`plan/ROADMAP.md`** — 実装済み一覧・P0/P1
6. **`plan/BLOG_CONTENT.md`** — コンテンツ戦略
7. **`plan/BLOG_CRON_GHA.md`** — GHA ワークフロー詳細（Fan-in Matrix）
8. **`plan/GLOSSARY.md`** — 用語定義
9. **`plan/VISION_AND_FUTURE.md`** — 構想・フェーズ
10. **`plan/INDEX.md`** — クイック参照（ファイルパス一覧）

---

## 9. 相談後の整理

返ってきたアドバイスは **`plan/ADVISORY_SYNTHESIS.md`** に構造化して記録する（ROADMAP 等と整合）。

---

*このファイルは `plan/BRIEFING_FOR_ADVISOR.md` として保存してある。更新時は日付と内容を合わせること。*
