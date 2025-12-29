# STATUS
Last updated: 2025-12-29 / commit: fb524be

## Now (SSOT)
- Supabase `/api/range` が実データを返すことを確認済み。
  - 例: `ts, store_id, src_brand, men, women, total, temp_c, precip_mm, weather_code, weather_label`
- Public facts の生成が動作。
  - `frontend/content/facts/public/*.json` (3件: 20251220/20251221/20251228)
  - `frontend/content/facts/public/index.json` (`generated_at: 2025-12-29`)
- Blog publish 例: `shibuya-tonight-20251228`。
- Blog draft/preview gate が有効（`BLOG_PREVIEW_TOKEN` 一致時のみ表示 + metadata も gate）。

## Done
- Next.js API routes が backend を proxy している (`/api/range`, `/api/forecast_*`, `/api/second_venues`)。
- Supabase → Flask → Next.js のレイヤ構造を維持。

## Next
- LINE/n8n は次スレで整理・実装。
- UI の仮表示/ダミーの整理。
