# 定時コンテンツ生成（GitHub Actions — 正本）

Last updated: 2026-03-26 (cron スケジュール / matrix 構成は引き続き有効)

> **2026-04 以降の内容更新**:
> - Daily Report のプロンプト改修は `plan/BLOG_REDESIGN_2026_04.md` を参照 (Phase 1 ✅ / Phase 3 cron 時間分散 ❌ 未着手)
> - Weekly Report の v2 redesign (ヒートマップ + AI 自然文 + 来週狙い目) は `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` を参照
> - generate-weekly-insights workflow に `INSIGHTS_GENERATE_AI_COMMENTARY=1` + `GEMINI_API_KEY` を追加済 (2026-05-03〜)

## 方針

- **Vercel Cron（`vercel.json`）は使わない**（二重実行防止のため削除済み）。
- **Daily Report**: `.github/workflows/trigger-blog-cron.yml` が **毎日 JST 18:00 / 21:30** に全 38 店舗を matrix で並列実行。
- **Weekly Report**: `.github/workflows/generate-weekly-insights.yml` が **毎週水曜 06:30 JST** に Fan-in Matrix 構成で全 38 店舗を並列生成。

---

## 1. Daily Report（`trigger-blog-cron.yml`）

### スケジュール（UTC）

| cron（UTC） | 日本時間 | edition |
|-------------|----------|---------|
| `0 9 * * *` | 毎日 18:00 JST | `evening_preview` |
| `30 12 * * *` | 毎日 21:30 JST | `late_update` |

### Matrix 構成

- **1 store = 1 独立ジョブ**（`strategy: matrix: store: [...]`）
- `fail-fast: false`（1店舗失敗でも他は止めない）
- `max-parallel: 15`（Render 負荷を考慮）
- `continue-on-error: true`（ジョブ失敗でも matrix 全体は継続）

### 実行フロー

1. `edition` と `trigger` を決定（schedule の cron パターンで分岐）
2. `GET <VERCEL_BLOG_CRON_BASE_URL>/api/cron/blog-draft?store=<slug>&edition=<edition>&source=github_actions_cron`
3. Supabase に `content_type='daily'`, `is_published=true` で保存

### 失敗店舗のみ再実行（手動）

- **Workflow**: `retry-blog-draft-stores.yml`
- **入力**: `edition`（定時と同じ）と `stores`（カンマ区切り、例: `nagasaki,fukuoka`）
- `source=github_actions_retry` を付与

### 部分失敗の監視

- `summarize-blog-matrix` ジョブがジョブ結論＋GitHub API で各 step まで確認
- `continue-on-error` でジョブが緑でも GET ステップ失敗（504 等）を拾う
- `OPS_NOTIFY_WEBHOOK_URL` 設定時は失敗店舗リストを Slack/Discord に通知

### 必要な Secrets

| 名前 | 内容 |
|------|------|
| `CRON_SECRET` | Vercel の `CRON_SECRET` と同じ値（`Authorization: Bearer` に使用）|
| `VERCEL_BLOG_CRON_BASE_URL` | 本番 URL（末尾スラッシュなし）|
| `OPS_NOTIFY_WEBHOOK_URL` | 任意。Slack/Discord Webhook URL |

---

## 2. Weekly Report（`generate-weekly-insights.yml`）— Fan-in Matrix

### スケジュール（UTC）

| cron（UTC） | 日本時間 |
|-------------|----------|
| `30 21 * * 2` | 毎週水曜 06:30 JST |

### Fan-in Matrix 構成

```
generate-store（Fan-out）
├─ strategy: matrix (38 stores)
├─ max-parallel: 10
├─ fail-fast: false
│
├─ [各 store ジョブ]
│   ├─ Python setup + requirements.txt
│   ├─ Warm up API endpoint
│   ├─ generate_weekly_insights.py --stores <store> --skip-index
│   │   ├─ /api/range から過去データ取得
│   │   ├─ Good Window 分析
│   │   ├─ JSON 出力（frontend/content/insights/weekly/<store>/）
│   │   └─ Supabase upsert (content_type='weekly', is_published=true)
│   └─ upload-artifact: weekly-<store>
│
collect-and-commit（Fan-in）
├─ download-artifact: pattern: weekly-*
├─ Python: artifacts をマージし index.json 再構築
├─ pytest -q
└─ git commit & push (1回のみ)
```

### `--skip-index` フラグの目的

並列実行時に複数ジョブが同時に `index.json` を書き込むと競合が発生するため、各 matrix ジョブは `--skip-index` を付けて `index.json` 更新をスキップ。Fan-in ジョブが全 Artifact の情報を元に `index.json` を一元マージして 1回だけ書き込む。

### store フィルタ（`workflow_dispatch` 時）

- `inputs.stores` が空 or `"all"` → 全 38 店舗を実行
- 特定店舗を指定（例: `"shibuya,fukuoka"`）→ 該当店舗のみ実行（他はスキップ）

### 必要な Secrets

| 名前 | 内容 |
|------|------|
| `SUPABASE_URL` | Supabase プロジェクトの URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role Key |
| `OPS_NOTIFY_WEBHOOK_URL` | 任意。Slack/Discord Webhook URL |

### Supabase 保存形式（Weekly）

| フィールド | 値 |
|-----------|-----|
| `content_type` | `'weekly'` |
| `is_published` | `true` |
| `edition` | `'weekly'` |
| `facts_id` | `'weekly_<store_slug>'` |
| `public_slug` | `'weekly-report-<store_slug>'` |

---

## 3. 成否の見方（共通）

- **GitHub の成否だけに依存しない。** 店舗ごとの真の状態は **Supabase `blog_drafts`**（`error_message` 等）で確認する。
- Daily: matrix は `continue-on-error` のため全体は緑になり得る。`summarize-blog-matrix` が部分失敗を判定。
- Weekly: Fan-out 内でジョブが失敗しても `fail-fast: false` で他ジョブは継続。Fan-in は `needs: generate-store` のため全ジョブ完了後に実行。
- 両ワークフロー失敗時は `notify-on-failure.yml` 経由で通知（`OPS_NOTIFY_WEBHOOK_URL` 設定時）。

---

## 4. Vercel 側の確認（任意）

過去に Vercel Cron を有効にしていた場合、ダッシュボード **Settings → Cron Jobs** に古いジョブが残っていれば**無効化または削除**してください（コード側の `vercel.json` は既に削除済み）。

---

## 5. 将来の非同期化

同期 HTTP の限界を超える場合の抜本案は **`plan/BLOG_CRON_ASYNC_FUTURE.md`**（未実装メモ）。
