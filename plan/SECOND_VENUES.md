# SECOND_VENUES
Last updated: 2026-03-21
Target commit: (see git)

## 方針
- 二次会スポットは map-link 方式が本流（frontend で Google Maps 検索リンクを生成）。
- Places API 依存 / DB 保存を前提にしない。
- `/api/second_venues` は補助的に残すが、本番 UX は使わない。

## 実装場所
- 設定: `frontend/src/app/config/secondVenueMapLinks.ts`
- Hook: `frontend/src/app/hooks/useSecondVenues.ts`
- UI: `frontend/src/components/SecondVenuesList.tsx`

## Backend (optional)
- `/api/second_venues` は最小応答（空配列）を返せればよい
- `GOOGLE_PLACES_API_KEY` がある場合のみ `/tasks/update_second_venues` を実行可能
