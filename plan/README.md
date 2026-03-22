# plan/ フォルダ案内（Cursor / AI 向け）
Last updated: 2026-03-21  
Target commit: (see git)

**迷ったら最初にこのファイルを読む。** 各 `.md` の役割と読了順を固定する。

---

## AI / 人間向け・推奨読了順

1. **`README.md`**（本ファイル）— どのファイルを見るか
2. **`CODEx_PROMPTS.md`** — 編集時のルール（API 契約・禁止事項）
3. **`STATUS.md`** — **いま動いている機能**（事実の正）
4. **`DECISIONS.md`** — 壊してはいけない判断
5. **`API_CONTRACT.md`** — Flask + Next `/api/line` の契約
6. **`ARCHITECTURE.md`** — データフロー
7. **`RUNBOOK.md`** — ローカル起動・本番メモ・**定期ジョブ**・トラブルシュート（旧 ONBOARDING / CRON を統合）
8. **`ENV.md`** — 環境変数
9. **`BLOG_PIPELINE.md`** — LINE → 下書き（技術）
10. **`BLOG_CONTENT.md`** — ブログ編集方針
11. **`BLOG_REQUEST_SCHEMA.md`** — 依頼 JSON のスキーマ（任意・契約）
12. **`SECOND_VENUES.md`** — 二次会 map-link 方針
13. **`VISION_AND_FUTURE.md`** — 構想・フェーズ・備忘
14. **`ROADMAP.md`** — 短いタスク一覧・当面やらないこと
15. **`CHECKLISTS.md`** — デプロイ前チェック

**用語が曖昧なとき**: `GLOSSARY.md`

---

## ファイル一覧（役割）

| ファイル | 役割 |
|----------|------|
| `README.md` | 本フォルダのナビ（**このファイル**） |
| `INDEX.md` | 主要パス・**Constraints** のクイック参照 |
| `GLOSSARY.md` | 用語（夜窓、`avoid_time` 等） |
| `CODEx_PROMPTS.md` | AI 作業ルール |
| `STATUS.md` | 稼働中機能の一覧 |
| `DECISIONS.md` | 不変の意思決定 |
| `API_CONTRACT.md` | API 契約 |
| `ARCHITECTURE.md` | アーキテクチャ |
| `RUNBOOK.md` | 起動・運用・**GitHub Actions / 外部 cron**・トラブルシュート |
| `ENV.md` | 環境変数 |
| `BLOG_PIPELINE.md` | LINE / Gemini / `blog_drafts` パイプライン |
| `BLOG_CONTENT.md` | ブログ・Facts の編集方針 |
| `BLOG_REQUEST_SCHEMA.md` | リクエスト JSON 契約 |
| `SECOND_VENUES.md` | 二次会スポット |
| `VISION_AND_FUTURE.md` | 展望・実装フェーズ |
| `ROADMAP.md` | P0/P1・やらないこと |
| `CHECKLISTS.md` | チェックリスト |
| `BRIEFING_FOR_ADVISOR.md` | 外部 AI 向け要約（相談用） |
| `ADVISORY_SYNTHESIS.md` | 外部アドバイス（Gemini 等）の整理・要約 |

**削除・統合済み**: `ONBOARDING.md` → `RUNBOOK.md` / `CRON.md` → `RUNBOOK.md` / `repo_map.txt` → 本 README と `INDEX.md`

---

## リポジトリの物理パス（よく触る場所）

- Backend: `app.py`, `oriental/`
- Collector: `multi_collect.py`
- Frontend: `frontend/src/`
- LINE 下書き: `frontend/src/app/api/line/route.ts`, `frontend/src/lib/blog/insightFromRange.ts`, `draftGenerator.ts`
- Workflows: `.github/workflows/`
- Supabase SQL: `supabase/migrations/`

HTTP スモーク用: `scripts/dev/smoke-requests.http`（旧 `plan/requests.http`）
