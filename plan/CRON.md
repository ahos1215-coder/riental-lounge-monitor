# CRON
Last updated: 2025-12-23
Target commit: 10e50d6

## GitHub Actions (repo managed)
- Generate Weekly Insights
  - Schedule: `30 15 * * 0` (UTC) = JST 月曜 00:30
  - Workflow: `.github/workflows/generate-weekly-insights.yml`
- Generate Public Facts
  - Schedule: `30 0 * * *` (UTC) = JST 09:30
  - Workflow: `.github/workflows/generate-public-facts.yml`
- Blog CI
  - Trigger: push / pull_request（schedule なし）
  - Workflow: `.github/workflows/blog-ci.yml`

## External Cron (ops managed)
- `/tasks/multi_collect` を 5 分間隔で叩く想定
  - 設定は運用側（Render / 外部 scheduler）
  - リポジトリ内に cron 定義は存在しない

## Not Implemented (if needed, add to ROADMAP)
- 追加の定期処理は未実装
