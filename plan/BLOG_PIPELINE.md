# MEGRIBI Blog Pipeline（LINE / Next.js / GitHub Actions / Supabase / GitHub）

最終更新: 2026-03-26 (本文の構造設計は引き続き有効)

> **2026-04 以降の内容更新**:
> - Daily Report のプロンプト / 出力スタイルは `plan/BLOG_REDESIGN_2026_04.md` (Phase 1 完了 / Phase 2-4 未着手) を正本として参照
> - Weekly Report の構造 (ヒートマップ / AI 自然文 / 来週狙い目 等) は `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` を正本として参照
> - 本ドキュメントの 3 分類 / URL / 基本フローは引き続き有効

## コンテンツの 3 分類（`blog_drafts.content_type`）

| `content_type` | 用途 | URL | 生成元 | `is_published` |
|----------------|------|-----|--------|----------------|
| `daily` | AI 予測予報（毎日 2 回） | `/reports/daily/[store_slug]` | GitHub Actions 定時 | 生成完了時に `true`（自動）|
| `weekly` | AI 週報（毎週水曜） | `/reports/weekly/[store_slug]` | GitHub Actions 週次 | 生成完了時に `true`（自動）|
| `editorial` | 分析ブログ記事（不定期）| `/blog/[slug]` | LINE 指示 + Gemini | 最初は `false`、LINE 承認で `true` |

**SEO 方針**: daily / weekly は **固定 URL 上書き**（同じ store_slug に対し最新行を上書き）。カニバリゼーションを避け、Freshness を優先。

---

## 配管の全体像（結論）
- **LINE 下書きの司令塔**: Next.js のみ（`POST /api/line`）。**n8n は廃止・非採用**。
- **バッチ（Daily / Weekly）**: GitHub Actions（`trigger-blog-cron.yml` / `generate-weekly-insights.yml`）
- **承認**: 人（LINE でテキスト承認）

## 役割
- あなた：分析依頼（LINE）→ 承認（LINE）→ 最終確認（公開 URL）
- LINE：指示 UI（スマホ）→ Webhook は **Vercel の Next のみ**
- Next.js：`POST /api/line` で受信 → 処理分岐 → Supabase `blog_drafts` 保存 → LINE 返信
- GitHub Actions：Daily / Weekly の自動生成
- Supabase：元データ（logs）、下書き（`blog_drafts`）
- GitHub：Weekly JSON ファイル置き場（`frontend/content/insights/weekly`）

---

## フロー 1: Daily Report（GitHub Actions → Supabase → `/reports/daily/`）

### 定時実行（`.github/workflows/trigger-blog-cron.yml`）
1. UTC 09:00（JST 18:00）/ UTC 12:30（JST 21:30）に発火
2. matrix で 38 店舗を並列実行（`max-parallel: 15`）
3. `GET /api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
4. `/api/cron/blog-draft/route.ts` 内で:
   - `/api/range` + `/api/forecast_today`（BACKEND_URL 経由）
   - `insightFromRange.ts` → Gemini MDX 生成
   - Supabase `blog_drafts` に upsert（`content_type='daily'`, `is_published=true`, `edition=<edition>`）
5. `/reports/daily/[store_slug]` が最新行を自動表示

**失敗時**: `retry-blog-draft-stores.yml` で該当店舗のみ再実行

---

## フロー 2: Weekly Report（GitHub Actions Fan-in → Supabase + Git → `/reports/weekly/`）

### Fan-out（`generate-store` ジョブ）
1. UTC 火曜 21:30（JST 水曜 06:30）に発火
2. matrix で 38 店舗を独立実行（`max-parallel: 10`）
3. `python scripts/generate_weekly_insights.py --stores <one_store> --skip-index`
   - `/api/range` から過去データ取得
   - Good Window 分析
   - `frontend/content/insights/weekly/<store>/<date>.json` に書き込み
   - Supabase upsert（`content_type='weekly'`, `is_published=true`, `edition='weekly'`, `facts_id='weekly_<store>'`, `public_slug='weekly-report-<store>'`）
4. JSON を Artifact としてアップロード（retention: 1日）

### Fan-in（`collect-and-commit` ジョブ）
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
