# 定時ブログ下書き（GitHub Actions — 正本）

Last updated: 2026-03-21

## 方針

- **Vercel Cron（`vercel.json`）は使わない**（二重実行防止のため削除済み）。
- **`.github/workflows/trigger-blog-cron.yml`** が **毎日 JST 18:00 / 21:30** に本番の `GET /api/cron/blog-draft` を叩く（UTC の cron で実現）。
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

手動実行は **Actions → Blog draft cron (GitHub Actions) → Run workflow** で `edition` を選択。

## Vercel 側の確認（任意）

過去に Vercel Cron を有効にしていた場合、ダッシュボード **Settings → Cron Jobs** に古いジョブが残っていれば **無効化または削除**してください（コード側の `vercel.json` は既に削除済み）。
