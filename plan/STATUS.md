# STATUS
Last updated: 2025-12-29 / commit: cf8c998

- Branch: main

## Working Now
- Supabase `/api/range` が実データを返すことを確認済み。
  - 例: `ts, store_id, src_brand, men, women, total, temp_c, precip_mm, weather_code, weather_label`
- Public facts 生成が動作。
  - `frontend/content/facts/public/*.json` (3件: 20251220/20251221/20251228)
  - `frontend/content/facts/public/index.json` の `generated_at: 2025-12-29`
- Blog publish 例: `shibuya-tonight-20251228` が公開状態。
- Blog draft/preview gate が有効（`BLOG_PREVIEW_TOKEN` 一致時のみ表示 + metadata も gate）。
- Next.js API routes が backend を proxy している（`/api/range`, `/api/forecast_*`, `/api/second_venues`）。

## Known Gaps / Next
- LINE/n8n の自動化は未実装（次スレで整理）。
- UI の一部に仮表示・ダミーが残る。
