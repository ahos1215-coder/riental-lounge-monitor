# ROADMAP
Last updated: 2025-12-29 / commit: fb524be

## Done (as of 2025-12-29)
- Supabase `logs` を source of truth に固定。
- `/api/range` の store/limit 契約を維持しつつ実データで動作確認。
- Next.js 16 App Router 構成が安定（`useSearchParams`/Suspense 対応済み）。
- Blog の draft/preview gate を厳密化（metadata も gate）。
- Public facts 生成 & `index.json` 自動生成を運用に組み込み、commit 済み。
- 公開ブログ例: `shibuya-tonight-20251228`。

## Next (P0)
- LINE → n8n の受け取りスキーマ確定と配管準備（`plan/BLOG_REQUEST_SCHEMA.md`）。
- facts → MDX ドラフト → PR の半自動化（最小安全な境界）。
- Public facts の対象拡張（複数 store / 日付）。

## Later
- UI 体験改善（読み込み体感・skeleton・キャッシュ方針）。
- Forecast 精度/運用の見直し。
