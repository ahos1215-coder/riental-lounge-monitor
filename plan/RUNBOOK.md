# RUNBOOK
Last updated: 2026-03-21
Target commit: (see git)

ローカル起動・本番メモ・**初回オンボーディング**・**定期処理（cron）**・トラブルシュート。  
（旧 `ONBOARDING.md` / `CRON.md` をここに統合）

---

## 初回オンボーディング（本番の心構え）

### Backend（Render / Flask）
- 常時起動想定。`DATA_BACKEND=supabase`。
- 環境変数例: `BACKEND_URL`（フロントから参照）、`SUPABASE_*`、`ENABLE_FORECAST`、`STORE_ID`、`MAX_RANGE_LIMIT=50000`（`plan/ENV.md`）。
- デプロイ後、`/tasks/tick` が一定間隔で動く構成があり得る（夜間も収集）。`ENABLE_FORECAST=1` のときのみ予測更新。

### Frontend（Vercel / Next.js 16）
- GitHub 連携 → main push でデプロイ。
- `BACKEND_URL` を Render の API に向ける。ブラウザから Supabase 直はしない。
- `useSearchParams` は `Suspense` 配下。Recharts Tooltip は型を拡張してビルド通過。

### LINE 下書き（本番）
- Messaging API の Webhook を **Vercel の `POST /api/line`** に。**n8n は使わない。**
- `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `GEMINI_API_KEY` / Supabase service role（`blog_drafts`）等は `plan/ENV.md`。

### Night window / 二次会 / Supabase
- 店舗 UI の夜 19:00–05:00 は **`useStorePreviewData.ts`**。LINE 下書きの窓は **`insightFromRange.ts`**。
- 二次会は **map-link**（`plan/SECOND_VENUES.md`）。
- `blog_drafts` は Next サーバー API のみが書き込み（service role）。

---

## Local Development

### Backend (Flask)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# .env に必要な環境変数を設定（plan/ENV.md 参照）
python app.py
```

### Frontend (Next.js)
```
cd frontend
npm install
# .env.local（ルート or frontend）— plan/ENV.md 参照
npm run dev
```

### 動作確認（ローカル）
- UI: `http://localhost:3000/?store=nagasaki` など
- 生データ: `http://127.0.0.1:5000/api/range?store=nagasaki&limit=400`

#### LINE 下書き・定時 Cron（ローカル）
1. Flask を起動（`BACKEND_URL` が `http://127.0.0.1:5000` になるよう `.env.local` を確認）
2. `frontend` で `npm run dev`
3. **LINE Webhook**: `.env.local` に `SKIP_LINE_SIGNATURE_VERIFY=1` を入れ、`POST http://localhost:3000/api/line` に LINE 形式の JSON を送る（`scripts/dev/smoke-requests.http` 参照）
4. **定時 Cron 相当**: `.env.local` に `SKIP_CRON_AUTH=1`（development のみ）を入れ、`GET http://localhost:3000/api/cron/blog-draft` を叩く。または `CRON_SECRET=test` と `Authorization: Bearer test` で叩く
5. Supabase を使う場合は `SUPABASE_*` と `GEMINI_API_KEY` を設定し、`blog_drafts` に行が増えることを確認
6. **自動スモーク（推奨）**: 別ターミナルで `cd frontend` のうえ  
   - `npm run smoke:blog-apis -- --quick` … `GET /api/line` と Cron の **401**（未認証）のみ  
   - `npm run smoke:blog-apis` … 上記に加え、`.env.local` の **`CRON_SECRET`**（Bearer）または **`SKIP_CRON_AUTH=1`** 時に **フル Cron**（Backend + Gemini + DB。最大約2分）

---

## Local Checks
- `/api/range?store=...&limit=...` が `ts` 昇順で返ること
- `/api/forecast_today?store=...`（`ENABLE_FORECAST=1` のとき）
- `/insights/weekly` が `index.json` を読めること
- LINE 下書き試験: `GET http://localhost:3000/api/line` がヘルス相当。`POST /api/line` は `SKIP_LINE_SIGNATURE_VERIFY=1` 等でローカル検証可能（`ENV.md`）
- 定時ブログ試験: `GET /api/cron/blog-draft?edition=evening_preview&source=github_actions_cron`（要 `CRON_SECRET` または development で `SKIP_CRON_AUTH=1`）。本番の定時は **GitHub Actions**（**`plan/BLOG_CRON_GHA.md`**）
- 一括: `cd frontend` → `npm run smoke:blog-apis -- --quick` / `npm run smoke:blog-apis`（`frontend/scripts/smoke-blog-apis.mjs`）

---

## 定期処理・GitHub Actions（旧 CRON.md）

### GitHub Actions（リポジトリ管理）
| 内容 | スケジュール | Workflow ファイル |
|------|----------------|---------------------|
| Weekly Insights | `30 15 * * 0` (UTC) = JST 月曜 00:30 | `.github/workflows/generate-weekly-insights.yml` |
| Public Facts | `30 0 * * *` (UTC) = JST 09:30 | `.github/workflows/generate-public-facts.yml` |
| Blog CI | push / PR（schedule なし） | `.github/workflows/blog-ci.yml` |
| **Blog cron（定時・本番）** | `0 9` / `30 12` UTC = JST 18:00 / 21:30 | `.github/workflows/trigger-blog-cron.yml` |

- Weekly: 手動 `workflow_dispatch` で `stores` / threshold 等を指定可能。成果物 `frontend/content/insights/weekly`
- Public Facts: 成果物 `frontend/content/facts/public`

### 外部 cron（運用側）
- **`/tasks/multi_collect`** を一定間隔で叩く想定。定義は **Render / 外部 scheduler**（リポジトリ内に crontab はない）。
- **ブログ下書き（1日2本・JST）**: **GitHub Actions**（`.github/workflows/trigger-blog-cron.yml`）が `GET /api/cron/blog-draft` を叩く。`?edition=evening_preview` / `late_update` と `source=github_actions_cron` を付与。**Secrets** は **`plan/BLOG_CRON_GHA.md`**。
- 追加の定期処理が必要なら `ROADMAP.md` に追記してから仕様化。

### 定時ブログ（GitHub Actions）のトラブルシュート

1. **Secrets**: GitHub → Repository → **Settings → Secrets and variables → Actions** に **`CRON_SECRET`** と **`VERCEL_BLOG_CRON_BASE_URL`**（本番の `https://...vercel.app`、末尾スラッシュなし）があるか。
2. **Actions の実行ログ**: 失敗時は `curl` の HTTP ステータス・Vercel 関数ログ（401 なら `CRON_SECRET` 不一致）。
3. **Vercel の古い Cron**: 過去に Vercel Cron を有効にしていた場合、ダッシュボード **Settings → Cron Jobs** に古いジョブが残っていれば **削除**（コード側は `vercel.json` なし）。

**正本**の手順・Secrets は **`plan/BLOG_CRON_GHA.md`**。

---

## Production Notes
- Backend: Render (Flask) / Frontend: Vercel (Next.js 16)
- Vercel に `BACKEND_URL` を設定
- LINE 下書き: `plan/ENV.md`。**n8n は使わない。**

---

## Troubleshooting
- `/api/range` が空: Supabase `logs` と `/tasks/multi_collect` を確認
- Forecast 503: `ENABLE_FORECAST=1`
- DNS エラー: URL を安易に変えず、ログで確認
- `/insights/weekly` が読めない: `index.json` の有無・JSON 破損
- **ブラウザで `/api/range` が 502**: Flask（`BACKEND_URL`、通常 `http://127.0.0.1:5000`）が起動していない、または URL が間違い。Flask を起動してから再読み込み。

### Next.js `npm run dev`（よくあるエラー）

1. **`cd frontend` で「パスが存在しません」**  
   すでに **`.../riental-lounge-monitor-main/frontend`** にいるときは **`cd frontend` をしない**（二重になる）。正しいカレントは `next.config.ts` と `package.json` がある **`frontend` 直下**。

2. **`Unable to acquire lock` … `is another instance of next dev running?`**  
   **別ターミナルで `next dev` が動いたまま**の可能性が高い。  
   - 不要なターミナルで **Ctrl+C** で停止する。  
   - 止まらない場合は **タスクマネージャー**で `Node.js` を終了。  
   - すべて止めたうえで、まだロックする場合のみ **`frontend/.next/dev/lock` を削除**（dev を起動していないときだけ）。

3. **`Port 3000 is in use` → 3001 で起動**  
   既に 3000 を使っているプロセスがある。上記と同様に **重複した `next dev` を止める**か、表示どおり **`http://localhost:3001`** で開く。

4. **`[baseline-browser-mapping] The data in this module is over two months old`**  
   **警告のみ**で開発は続行可。消したい場合（任意）: `cd frontend` → `npm i baseline-browser-mapping@latest -D`。

---

## HTTP スモーク（VS Code REST Client）
`scripts/dev/smoke-requests.http` を参照。

## ブログ下書きの Git 用エクスポート（Supabase → ローカル）
- `cd frontend` のうえで `npm run drafts:export`（要 `.env.local` の service role）。詳細は `plan/BLOG_PIPELINE.md` §3b。
