# MEGRIBI Blog Pipeline（ローカル Ollama / LINE / Next.js / GitHub Actions / Supabase / GitHub）

最終更新: 2026-07-11（Batch B3: Daily/Weekly の生成元をローカル Ollama 主経路に更新。3分類・URL・LINE フローの構造自体は変わっていない）

> **2026-07〜の変更**: Daily / Weekly の生成元は **GitHub Actions + Gemini から ローカル Ollama
> （`gemma4:e4b`）へ主経路が移行済み**。GitHub Actions は `workflow_dispatch` の緊急用のみ残る。
> 詳細手順は `docs/LOCAL_LLM_SETUP.md`、GHA 側の緊急手順は `plan/BLOG_CRON_GHA.md` を参照。

> **2026-04 以降の内容更新**:
> - Daily Report のプロンプト / 出力スタイルは `plan/BLOG_REDESIGN_2026_04.md` (Phase 1 完了 / Phase 2-4 未着手) を正本として参照
> - Weekly Report の構造 (ヒートマップ / AI 自然文 / 来週狙い目 等) は `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` を正本として参照
> - 本ドキュメントの 3 分類 / URL / 基本フローは引き続き有効

## コンテンツの 3 分類（`blog_drafts.content_type`）

| `content_type` | 用途 | URL | 生成元 | `is_published` |
|----------------|------|-----|--------|----------------|
| `daily` | AI 予測予報（毎日 2 回） | `/reports/daily/[store_slug]` | **ローカル Ollama 定時（主）** / GHA `workflow_dispatch`（緊急時） | 生成完了時に `true`（自動）|
| `weekly` | AI 週報（毎週水曜） | `/reports/weekly/[store_slug]` | **ローカル Ollama 定時（主）** / GHA `workflow_dispatch`（緊急時） | 生成完了時に `true`（自動）|
| `editorial` | 分析ブログ記事（不定期）| `/blog/[slug]` | LINE 指示 + Gemini | 最初は `false`、LINE 承認で `true` |

**SEO 方針**: daily / weekly は **固定 URL 上書き**（同じ store_slug に対し最新行を上書き）。カニバリゼーションを避け、Freshness を優先。

---

## 配管の全体像（結論）
- **LINE 下書きの司令塔**: Next.js のみ（`POST /api/line`）。**n8n は廃止・非採用**。
- **バッチ（Daily / Weekly）**: **ローカル Ollama（主。`scripts/local_report_job.py` / `run_weekly_local.ps1`、Task Scheduler）**。GitHub Actions（`trigger-blog-cron.yml` / `generate-weekly-insights.yml`）は `workflow_dispatch` の緊急用のみ
- **承認**: 人（LINE でテキスト承認）

## 役割
- あなた：分析依頼（LINE）→ 承認（LINE）→ 最終確認（公開 URL）
- LINE：指示 UI（スマホ）→ Webhook は **Vercel の Next のみ**
- Next.js：`POST /api/line` で受信 → 処理分岐 → Supabase `blog_drafts` 保存 → LINE 返信
- ローカル Ollama（オーナーPC）：Daily / Weekly の自動生成（主経路）
- GitHub Actions：Daily / Weekly の緊急時再生成（`workflow_dispatch`）、Editorial 以外の監視・CI 全般
- Supabase：元データ（logs）、下書き（`blog_drafts`）
- GitHub：Weekly JSON ファイル置き場（`frontend/content/insights/weekly`）

---

## フロー 1: Daily Report（ローカル Ollama → Supabase → `/reports/daily/`）

### 定時実行（主経路: Task Scheduler `MEGRIBI-daily-evening` / `MEGRIBI-daily-late`）
1. 毎日 JST 18:00（evening_preview）/ 21:30（late_update）に発火
2. `scripts/local_report_job.py --stores all --edition <edition> --mode publish` が全43店舗を単一プロセスで順次処理
3. `/api/range` + `/api/forecast_today` 相当のデータ取得 → Ollama（`gemma4:e4b`）で本文生成
4. Supabase `blog_drafts` に upsert（`content_type='daily'`, `is_published=true`, `edition=<edition>`）。失敗時は本文空・`is_published=false`・`error_message` あり
5. `/reports/daily/[store_slug]` が最新行を自動表示

### 緊急時経路（`.github/workflows/trigger-blog-cron.yml`, `workflow_dispatch` のみ）
1. `EDITION` を手動指定して起動
2. matrix でオリエンタル 38 店舗を並列実行（`max-parallel: 5`。相席屋5店舗は対象外）
3. `GET /api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
4. `/api/cron/blog-draft/route.ts` 内で Gemini MDX 生成 → Supabase `blog_drafts` に upsert

**失敗時**: `retry-blog-draft-stores.yml` で該当店舗のみ再実行（いずれの経路でも）

---

## フロー 2: Weekly Report（ローカル Ollama → Supabase + Git → `/reports/weekly/`）

### 定時実行（主経路: Task Scheduler `MEGRIBI-weekly`）
1. 毎週水曜 JST 06:30 に発火
2. `run_weekly_local.ps1 -Stores all` → `generate_weekly_insights.py --stores all`（`INSIGHTS_LLM_BACKEND=ollama`）が全43店舗を単一プロセスで順次処理
3. `/api/range` から過去データ取得 → Good Window 分析 → `frontend/content/insights/weekly/<store>/<date>.json` に書き込み + `index.json` を直接更新（Fan-in 不要）
4. Supabase upsert（`content_type='weekly'`, `is_published=true`, `edition='weekly'`, `facts_id='weekly_<store>'`, `public_slug='weekly-report-<store>'`）

### 緊急時経路（`generate-weekly-insights.yml`, `workflow_dispatch` のみ）— Fan-in Matrix

#### Fan-out（`generate-store` ジョブ）
1. 手動起動時、matrix でオリエンタル 38 店舗を独立実行（`max-parallel: 10`。相席屋5店舗は対象外）
2. `python scripts/generate_weekly_insights.py --stores <one_store> --skip-index`（`INSIGHTS_LLM_BACKEND=gemini`）
3. JSON を Artifact としてアップロード（retention: 1日）

#### Fan-in（`collect-and-commit` ジョブ）
1. 全 Artifact ダウンロード
2. Python inline スクリプトで `index.json` を再構築（全店舗マージ）
3. `pytest` 実行
4. `git commit && git push`（1回のみ）

`/reports/weekly/[store_slug]` は Supabase から最新行を表示。`/insights/weekly/[store]` は JSON ファイル（Recharts 可視化）。

---

## フロー 3: Editorial Blog（LINE → Gemini → Supabase → LINE 承認 → `/blog/[slug]`）

### 3a) 分析依頼（`editorial_analysis` / `draft` インテント）

1. LINE で「○○について分析して」「渋谷店のレポート作って」等を送信
2. `POST /api/line` → `parseLineIntent.ts` → `editorial_analysis` or `draft` インテント
3. `handleDraftOrEditorialIntent`:
   - `BACKEND_URL` + `GET /api/range?store=...&limit=<LINE_RANGE_LIMIT=500>`
   - 必要に応じ `GET /api/forecast_today`
   - `insightFromRange.ts`：今夜窓（JST 19:00〜翌 05:00）。窓内が空なら全日フォールバック
   - `draftGenerator.ts`：Gemini MDX 下書き生成
   - Supabase `blog_drafts` に保存（**`content_type='editorial'`, `is_published=false`**、`public_slug` 自動生成）
4. LINE 返信：「下書きを作成しました。内容を確認後、『公開』と送ってください。」

### 3b) 承認・公開（`approve` インテント）

1. LINE で「公開」「ok」「承認」等を送信
2. `POST /api/line` → `parseLineIntent.ts` → `approve` インテント
3. `handleApproveIntent`:
   - `fetchLatestUnpublishedEditorialByLineUser(lineUserId)` で最新の未公開 editorial を特定
   - `publishEditorialBySlug(publicSlug)` → `is_published=true` に更新
4. LINE 返信：公開 URL（`https://www.meguribi.jp/blog/<public_slug>`）

### 3c) 公開ページ（`/blog/[slug]`）
- `fetchPublishedEditorialBySlug(slug)` で Supabase から取得
- `content_type='editorial'` かつ `is_published=true` の行のみ表示
- 存在しない場合は `notFound()`

---

## Supabase `blog_drafts` の保存ルール（`runBlogDraftPipeline.ts`）

| `source` | `content_type` | `is_published` |
|----------|----------------|----------------|
| `github_actions_cron` | `daily` | `true` |
| `github_actions_retry` | `daily` | `true` |
| `vercel_cron` | `daily` | `true` |
| `line_webhook`（editorial 指示）| `editorial` | `false` |
| `line_webhook`（draft）| `editorial` | `false` |

---

## ローカル運用（Editorial のエクスポート）

```powershell
cd frontend
npm run drafts:export -- --list
npm run drafts:export -- --latest --force
```

出力先:
- `frontend/content/blog/<facts_id>.mdx`
- `frontend/content/facts/public/<facts_id>.json`

オプション: `--dry-run` / `--update-index` / `--force`

---

## 廃止したもの

- **n8n** による LINE 受付 / Actions 起動 / 各種通知。**採用しない**。
- **`/blog/auto-[store]-[slot]`** URL。`/reports/daily/[store_slug]` に移行済み。
- **`fetchLatestAutoBlogDrafts`** 関数の UI 使用（`blog/page.tsx` から削除済み）。関数自体は下位互換のため残存。
