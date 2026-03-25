# 定時ブログ下書き（GitHub Actions — 正本）

Last updated: 2026-03-25

## 方針

- **Vercel Cron（`vercel.json`）は使わない**（二重実行防止のため削除済み）。
- **`.github/workflows/trigger-blog-cron.yml`** が **毎日 JST 18:00 / 21:30** に本番の `GET /api/cron/blog-draft` を叩く（UTC の cron で実現）。**1 店舗 = 1 並列ジョブ**（matrix）。
- エンドポイントはクエリで **`edition`** と **`source=github_actions_cron`** を付与する。
  - **18:00 JST** → `evening_preview`（18時便）
  - **21:30 JST** → `late_update`（21時半便）

## GitHub リポジトリで設定する値（最終リスト）

### Secrets（必須）

| 名前 | 内容 |
|------|------|
| **`CRON_SECRET`** | Vercel プロジェクトの **Environment Variables** にある `CRON_SECRET` と**同じ値**。`Authorization: Bearer` に使う。 |
| **`VERCEL_BLOG_CRON_BASE_URL`** | 本番のベース URL。**末尾スラッシュなし**（例: `https://your-app.vercel.app`）。 |

### Variables

**不要**です（旧 `BLOG_CRON_GHA_ENABLED` は廃止しました）。

## スケジュール（UTC）

GitHub Actions の `schedule` は **UTC のみ**です（日本は夏時間なしのため JST = UTC+9 固定）。

| cron（UTC） | 日本時間 | edition |
|-------------|----------|---------|
| `0 9 * * *` | 毎日 18:00 JST | `evening_preview` |
| `30 12 * * *` | 毎日 21:30 JST | `late_update` |

手動実行は **Actions → Blog draft cron (GitHub Actions) → Run workflow** で `edition` を選択（**全店舗**が対象）。

## 失敗店舗のみ再実行（手動）

- **Workflow**: **Retry blog draft (selected stores)**（`.github/workflows/retry-blog-draft-stores.yml`）
- **用途**: Supabase `blog_drafts` で `error_message` がある店舗など、**指定した slug だけ**を再度 `GET /api/cron/blog-draft` する。`source=github_actions_retry` を付与する。
- **入力**: `edition`（定時と同じ）と `stores`（カンマ区切り、例: `nagasaki,fukuoka`）。
- 必要な Secrets は定時と同じ（`CRON_SECRET`, `VERCEL_BLOG_CRON_BASE_URL`）。

## 成否の見方（監視）

- **GitHub の成否だけに依存しない。** 店舗ごとの真の状態は **Supabase `blog_drafts`**（`error_message` 等）で確認する。
- **一部店舗だけ失敗**した場合、matrix は `continue-on-error` のため**全体は緑**になり得る。Repository Secret **`OPS_NOTIFY_WEBHOOK_URL`**（任意）を設定していれば、失敗した店舗を列挙した **部分失敗通知**（`notify-partial-blog-failures` → `notify-on-failure.yml` の `custom_body`）が送られる。
- 運用手順の要約はリポジトリ直下 **`STATUS.md`**（**定時 Cron 実行後のチェックリスト**あり）。将来、同期 HTTP の限界を超える場合の抜本案は **`plan/BLOG_CRON_ASYNC_FUTURE.md`**。

## Vercel 側の確認（任意）

過去に Vercel Cron を有効にしていた場合、ダッシュボード **Settings → Cron Jobs** に古いジョブが残っていれば **無効化または削除**してください（コード側の `vercel.json` は既に削除済み）。
