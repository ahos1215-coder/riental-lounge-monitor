# plan/ フォルダ案内（Cursor / AI 向け）
Last updated: 2026-07-11（Batch B3: BLOG_CRON_GHA.md の位置づけ修正・CLAUDE.md 追加を反映）
Target commit: (see git)

**迷ったら最初にこのファイルを読む。** 各 `.md` の役割と読了順を固定する。

> **リポジトリ全体の3分マップは `../CLAUDE.md`（リポジトリ直下）にある。** 本 `plan/` 配下は
> その深掘り版（設計判断の経緯・契約の詳細・過去の Round 記録）。まず `CLAUDE.md` → 必要に応じて
> 本ファイル経由で各 `plan/*.md` へ、という順で読むこと。

---

## AI / 人間向け・推奨読了順

0. **`../CLAUDE.md`**（リポジトリ直下）— システム全体の3分マップ（最初に読む）
1. **`README.md`**（本ファイル）— どのファイルを見るか
2. **`CODEx_PROMPTS.md`** — 編集時のルール（API 契約・禁止事項）
3. **`ARCHITECTURE.md`** — データフロー全量・Key Files
   （旧3位の `STATUS.md` は 2026-05-05 で更新停止したスナップショット。稼働実態は `../CLAUDE.md` が正本）
4. **`DECISIONS.md`** — 壊してはいけない判断
5. **`API_CONTRACT.md`** — Flask + Next `/api/line` の契約
6. **`API_CURRENT.md`** — `/api/current` の位置づけ（補足）
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
| `STATUS.md` | 稼働中機能の一覧（**2026-05-05 のスナップショット。38店舗・v6 等は古い**。正本は `../CLAUDE.md`） |
| `DECISIONS.md` | 不変の意思決定 |
| `API_CONTRACT.md` | API 契約 |
| `API_CURRENT.md` | `/api/current` の位置づけ・当面方針 |
| `ARCHITECTURE.md` | アーキテクチャ |
| `RUNBOOK.md` | 起動・運用・**GitHub Actions / 外部 cron**・トラブルシュート |
| `BLOG_CRON_GHA.md` | 定時ブログの **GitHub Actions 緊急時手順**（`workflow_dispatch`）・Secrets 一覧。**通常運用の正本ではない** — 通常運用（ローカル Ollama 主経路）の正本は `../docs/LOCAL_LLM_SETUP.md` |
| `BLOG_CRON_ASYNC_FUTURE.md` | 定時ブログの **非同期化・キュー**（将来案メモ。未実装） |
| （リポジトリ直下）`../STATUS.md` | 定時ブログの **監視・成功の定義・失敗店舗の再実行**（運用要約。**GHA が主経路だった頃のメモ**で、現行の主経路はローカル Ollama） |
| `ENV.md` | 環境変数 |
| `BLOG_PIPELINE.md` | LINE / Gemini / `blog_drafts` パイプライン |
| `BLOG_CONTENT.md` | ブログ・Facts の編集方針 |
| `BLOG_REQUEST_SCHEMA.md` | リクエスト JSON 契約 |
| `SECOND_VENUES.md` | 二次会スポット |
| `VISION_AND_FUTURE.md` | 展望・実装フェーズ |
| `ROADMAP.md` | P0/P1・やらないこと |
| `WEEKLY_INSIGHTS_TUNING.md` | 週次 Insights の閾値・GHA 環境変数・調整タイミング |
| `FORECAST_V2.md` | v2 shadow パイプライン（snapshot → score → templates）の設計 |
| `FORECAST_ACCURACY.md` | 予測の答え合わせ運用・精度指標の読み方 |
| `CDN_WARMING_LOCAL.md` | CDN warming をローカル Task Scheduler へ移した経緯・登録手順 |
| `LOGS_BACKUP.md` | Supabase `logs` のバックアップ運用メモ |
| `BLOG_REDESIGN_2026_04.md` | （履歴）ブログ改修の記録 |
| `WEEKLY_REPORT_REDESIGN_2026_05.md` | （履歴）週報 v2 改修の記録 |
| `CHECKLISTS.md` | チェックリスト |
| `BRIEFING_FOR_ADVISOR.md` | 外部 AI 向け要約（相談用） |
| `ADVISORY_SYNTHESIS.md` | 外部アドバイス（Gemini 等）の整理・要約 |
| `GEMINI_REVIEW_PROMPT.md` | Gemini レビュー用プロンプト |

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
