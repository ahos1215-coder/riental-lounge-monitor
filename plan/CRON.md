# CRON
Last updated: 2025-12-29 / commit: cf8c998

## Current (production assumption)
- `/tasks/multi_collect` を定期実行して Supabase `logs` に書き込む。
  - 目安: 5分間隔 / 夜窓(19:00-05:00)に合わせて運用側で制御。
- `/tasks/tick` は legacy（単店 + ローカル/GAS向け）。Supabase の主経路ではない。

## Manual / On-demand
- `/tasks/update_second_venues` は `GOOGLE_PLACES_API_KEY` がある場合のみ実行。

## Not Automated Yet
- Public facts 生成: `npm run facts:generate` + `node scripts/build-public-facts-index.mjs`
- Blog publish: draft → review → `draft` を外して公開
