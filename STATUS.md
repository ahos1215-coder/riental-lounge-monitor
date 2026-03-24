# STATUS

## Blog Draft Cron Monitoring

- `Blog draft cron` の成否判定は GitHub Actions の終了ステータスだけに依存しない。
- 正本は Supabase `blog_drafts` の最新行とし、`error_message` の有無で店舗単位に確認する。
- GitHub Actions 側は実行オーケストレーション（起動・再試行）の役割とする。
- 運用時は「対象日付 + 店舗slug」で `blog_drafts` を確認し、欠損または `error_message != null` の店舗のみ再実行する。
