# CODEX_PROMPTS

Guidance for GPT-5.1-Codex-Max on MEGRIBI.
Last updated: TODO, commit: TODO

## Core Principles
- Source of truth: Supabase `logs` / `stores`. Google Sheet/GAS is legacy fallback only.
- Architecture: Supabase -> Flask API (Render) -> Next.js 16 frontend (Vercel).
- `/api/range`: only `store` + `limit`; no `from/to`. Supabase queried `ts.desc`, response sorted `ts.asc`. **Backendは夜間(19:00-05:00)フィルタ禁止**; 夜判定はフロント専任。
- `max_range_limit = 50000`; frontend推奨 200-400.
- Forecast APIs gated by `ENABLE_FORECAST=1`.
- Store resolution: `?store=` overrides env default.
- Second venues: **map-link frontend only** (Google Maps search links). Backend/Supabase/Places API を使う実装に戻さない。

## Frontend Rules
- Next.js 16 App Router: `useSearchParams` / `useRouter` を使うコンポーネントは必ず `Suspense` 配下に置く。
- Recharts `TooltipProps` には `label`/`payload` が型定義されていないため、独自型で拡張して使う（例: `label?: string | number; payload?: any[];`）。
- Night window (19:00-05:00) は `useStorePreviewData.ts` の責務。サーバー側で時間フィルタを入れない。

## Backend Rules
- 主要エンドポイント `/healthz`, `/api/meta`, `/api/current`, `/api/range`, `/api/forecast_*`, `/tasks/tick` の契約を壊さない。
- `/api/range` にサーバー側時間絞り込みを入れない。クエリ追加は禁止（store/limitのみ）。
- 機密値は環境変数経由で扱い、ハードコード禁止。

## Modes the model must follow
- [BUGFIX]: ログ/テストから原因候補を列挙→期待挙動を明文化→修正方針→最小diff→実行コマンド提示。DNS系はコード変更前に「ローカルDNSの可能性」「本番での再現確認」を案内。
- [FEATURE]: 仕様と plan/* 整合を確認→設計メモ→diff→追加テスト案/requests.http案。
- [REFACTOR]: 目的を明示→互換性確認→小さなステップに分解しdiff提示。
- [DOC]: 実装との差分を指摘→必要箇所に Last updated/commit を追記するdiff。
- [EXPLAIN]: 役割/データフロー説明のみ。diffは出さない。

## Prohibited / Caution
- DNS/ENOTFOUND系エラー時にホスト名やコードを書き換えない。まず本番(Render/Vercel)での再現確認を提案。
- フロントから直接 Supabase へアクセスさせない。
- `/api/range` に from/to や夜間フィルタを追加しない。
- Legacy Google Sheet/GAS を拡張しない。
- 二次会スポットを Places API や Supabase連携に戻さない（map-link方針を維持）。

## Good Prompt Examples
- "Update `/api/range` handler to keep legacy fallback but skip any time filtering; Supabase newest-first, respond asc."
- "Add brand metadata to `stores` table while keeping store IDs stable; brands: Oriental / Aisekiya / JIS."
- "Ensure frontend night window (19:00-05:00) stays intact while adding a new series."
- "Keep second-venue feature as Google Maps search links; no Places API, no backend changes."
