# CODEx_PROMPTS
Last updated: 2025-12-29 / commit: fb524be

MEGRIBI の開発補助 AI (Codex) 向けガイドライン。既存の決定事項と契約を壊さないこと。

## Start Here (初見のChatGPT / Codex向け)
1) `README.md`
2) `plan/INDEX.md`
3) `plan/STATUS.md`
4) `plan/DECISIONS.md`
5) `plan/API_CONTRACT.md`
6) `plan/ARCHITECTURE.md`
7) `plan/RUNBOOK.md`
8) `plan/ENV.md` / `plan/CRON.md`
9) `plan/SECOND_VENUES.md`
10) `plan/ROADMAP.md`

補助: `plan/repo_map.txt` があれば先に見る。

## SSOT (正本) の扱い
- 実装の事実はコードが正。
- 設計意図・制約は plan/*.md が正。
- 食い違いがあれば plan を更新して整合させる（コード修正は別判断）。

## Core Constraints (絶対に壊すな)
- `/api/range` 公開契約は `store` + `limit` のみ。サーバ側の時間フィルタは追加しない。
- 夜窓(19:00-05:00)の絞り込みはフロント責務（`useStorePreviewData.ts` / facts生成スクリプト）。
- Supabase logs が唯一の source of truth。
- Supabase → Flask → Next.js のレイヤ構造を維持（フロントから直叩きしない）。
- Second venues は map-link 方針（Places API 収集・保存型に戻さない）。
- Secrets をハードコードしない（`NEXT_PUBLIC_*` に秘密値禁止）。

## Frontend Rules (Next.js 16 / App Router)
- `useSearchParams` / `useRouter` を使うコンポーネントは `Suspense` 配下に置く。
- Blog の draft/preview gate は `BLOG_PREVIEW_TOKEN` の一致のみ有効。metadata も同じ gate。
- Public facts は `frontend/content/facts/public/` に commit する前提。

## Backend Rules (Flask)
- `DATA_BACKEND=supabase` が基本。Supabase 設定が無い場合のみ legacy に fallback。
- Forecast は `ENABLE_FORECAST=1` のときのみ有効。
- 本番収集の入口は `/tasks/multi_collect`（`/tasks/tick` は legacy）。

## PowerShell Notes
- `python - << 'PY'` は動かない。here-string を `python -` に渡す:
```powershell
@'
print("hello")
'@ | python -
```
- `&` を含む URL は必ず引用符で囲む（`curl.exe "http://...&..."`）。
- Desktop が OneDrive にリダイレクトされる場合があるため、`[Environment]::GetFolderPath("DesktopDirectory")` を使う。

## Env Pitfalls
- `.env` は **UTF-8 no BOM** で保存。BOM があると `\ufeffSUPABASE_URL` になり読めない事故が起きる。
- Supabase Python SDK は不要（Python 3.14 で依存関係が失敗しやすい）。REST (`requests`) を使う。

## Modes
- [DOC] plan/*.md や README の更新・同期
- [BUGFIX] テスト失敗/例外/HTTP 500 などの修正
- [FEATURE] 新機能追加/挙動変更
- [REFACTOR] 構造整理/責務分離
- [EXPLAIN] 説明だけ（diff を出さない）
