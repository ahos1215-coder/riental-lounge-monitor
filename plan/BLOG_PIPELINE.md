# MEGRIBI Blog Pipeline（LINE / Next.js / GitHub Actions / Supabase / GitHub）

最終更新: 2026-03-21

## 配管の全体像（結論）
- **LINE 下書きの司令塔**: Next.js のみ（`POST /api/line`）。**n8n は廃止・非採用**（ワークフロー・キュー・通知用に置かない）。
- **バッチ（週次・Facts）**: GitHub Actions（実行環境）
- **資産**: Supabase（`logs` / `blog_drafts`） / GitHub（記事・画像・公開 Facts）
- **承認**: 人（PR マージ＝公開許可）

## 役割
- あなた：最終承認（PR マージ）
- LINE：指示 UI（スマホ）→ Webhook は **Vercel の Next のみ**
- Next.js：`POST /api/line` で受信 → `BACKEND_URL` 経由で Flask `/api/range` 等で材料取得 → **`insightFromRange.ts`** でインサイト → **Gemini**（`draftGenerator.ts`）で MDX 下書き → Supabase **`blog_drafts`** 保存 → LINE 返信
- GitHub Actions：週次 Insights / Public Facts 生成・`blog-ci`（**n8n から起動しない**）
- Supabase：元データ（logs）、下書き（`blog_drafts`）
- GitHub：成果物置き場（MDX / 画像 / 公開 Facts）＋承認ゲート（PR）

## 現行フロー（MVP・LINE 下書き）

### 1) 指示（人が動かすのはここだけ）
- LINE → Next.js `POST /api/line`（Messaging API の Webhook URL を Vercel に設定）

### 2) Next.js 内処理（自動）
- 署名検証（本番は `LINE_CHANNEL_SECRET`）
- `parseLineIntent`（`frontend/src/lib/line/parseLineIntent.ts`）で店舗・日付・レベル等を解釈
- `BACKEND_URL` + `GET /api/range?store=...&limit=...`（`limit` は **`LINE_RANGE_LIMIT`**（既定 500）。`frontend/src/app/api/line/route.ts`）
- 必要に応じ `GET /api/forecast_today`
- `insightFromRange.ts`：**今夜窓**（JST 当日 19:00〜翌 05:00）。窓内が空なら **同一日の全日（JST）** にフォールバック
- `draftGenerator.ts`：既定 Gemini モデル **`gemini-2.5-flash`**（404 時は `gemini-2.5-flash-lite` 等。429 はリトライ）
- Supabase `blog_drafts` に保存（`SUPABASE_SERVICE_ROLE_KEY` 等）
- LINE に短い返信

### 2b) 定時ブログ（GitHub Actions — 正本）
- **`.github/workflows/trigger-blog-cron.yml`** が `GET /api/cron/blog-draft` を実行（JST 18:00 / 21:30 に相当する UTC cron）。クエリで **`edition`**（`evening_preview` / `late_update`）と **`source=github_actions_cron`** を付与。詳細 **`plan/BLOG_CRON_GHA.md`**。認証は **`CRON_SECRET`**（`Authorization: Bearer`）。
- 店舗は **`BLOG_CRON_STORE_SLUG(S)`**、当日日付は JST の「今日」（`?date=YYYY-MM-DD` で上書き可）。
- データ取得の `limit` は **`BLOG_CRON_RANGE_LIMIT`**（既定 500）。保存先・MDX 生成は LINE と同じ。`blog_drafts.source` は **`github_actions_cron`**。
- **18:00 JST** 便 → `evening_preview`（事前予報）、**21:30 JST** 便 → `late_update`（実況）。GHA から **`?edition=`** で明示するため、サーバ時刻のズレに依存しない。

### 3) 公開（GitHub 経由・運用タスク）
- 下書きを MDX に昇格し PR する、などは **人手・別タスク**（`plan/BLOG_CONTENT.md` / `plan/BLOG_REQUEST_SCHEMA.md` の命名・ID ルールを参照）。
- **SEO・同一 URL 上書き・Cron スケール・X 投稿スコープ**の方針は **`plan/VISION_AND_FUTURE.md` §9**（全店展開を見据えた記録）。

### 3b) Supabase → ローカル MDX / 公開 Facts（CLI）
- **人が内容を確認したあと**、ローカルに書き出して `git add` → PR する想定（フル自動公開はしない）。
- スクリプト: `frontend/scripts/export-blog-draft.mjs`
- ルートの `.env.local` に `SUPABASE_URL` と **`SUPABASE_SERVICE_ROLE_KEY`**（または `SUPABASE_SERVICE_KEY`）が必要（REST で `blog_drafts` を読む）。

```powershell
cd frontend
npm run drafts:export -- --list
npm run drafts:export -- --latest --force
# または ID 指定
npm run drafts:export -- --id=4cee2233-99e1-43f9-b3a8-94267253b0a1 --force
```

- 出力先:
  - `frontend/content/blog/<facts_id>.mdx`（`mdx_content` そのまま）
  - `frontend/content/facts/public/<facts_id>.json`（`insight_json` を公開用 shape に正規化）
- オプション: `--dry-run`（表示のみ） / `--update-index`（`facts/public/index.json` にエントリ追加・重複時はスキップ）
- 既存ファイルがある場合は **`--force` で上書き**（誤爆防止のため既定は拒否）。

## 公開 Facts 生成（ローカル）
- MDX frontmatter の date/store から夜窓（19:00–翌05:00 JST）を計算し、insight を自動生成する。
- 実行場所は repo root / `frontend` どちらでも可（`content/blog` を自動検出）。
- `/api/range?store=...&limit=1000` を優先し、窓内が空なら `/api/forecast_today` を使う。forecast の日付ズレは +1 日シフトで救済する。

```powershell
cd frontend
npm run facts:generate -- --slug shibuya-tonight-20251221 --backend http://127.0.0.1:5000
```

## GitHub Actions（バッチのみ）
- **Weekly Insights**: `Generate Weekly Insights`（週次・`frontend/content/insights/weekly`）
- **Public Facts**: `Generate Public Facts`（日次・`frontend/content/facts/public`）
- **blog-ci**: push / PR で `frontend` 変更時に CI

## 廃止したもの（方針）
- **n8n** による LINE 受付 / Actions 起動 / 各種通知。**採用しない**。
