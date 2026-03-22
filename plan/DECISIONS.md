# DECISIONS
Last updated: 2026-03-21
Target commit: (see git)

## Core decisions (keep)
1) Supabase `logs` が唯一の Source of Truth。Google Sheet / GAS は legacy fallback（拡張禁止）。
2) レイヤ構造は Supabase → Flask → Next.js（Next API routes は proxy）。フロントから Supabase 直アクセスしない。
3) `/api/range` の公開契約は `store` + `limit` のみ。サーバ側の時間フィルタは入れない。Supabase は `ts.desc` 取得 → `ts.asc` 返却。
4) **夜窓（19:00–05:00）の判定・絞り込み**
   - **店舗プレビュー UI**: フロント責務（`frontend/src/app/hooks/useStorePreviewData.ts`）。
   - **LINE ブログ下書き**: 取得済み `/api/range` の JSON に対して **`insightFromRange.ts`（Next サーバー）** で窓計算・集計。Flask の `/api/range` 契約は不変（**サーバ側に夜窓フィルタを足さない**）。
5) 二次会スポットは map-link 方式が本流。Places API 依存 / DB 保存前提に戻さない。`/api/second_venues` は最小応答の維持のみ。
6) Forecast は `ENABLE_FORECAST=1` のときのみ有効（無効時は 503）。
7) 収集の主系入口は `/tasks/multi_collect`（alias: `/api/tasks/collect_all_once`）。`/tasks/tick` と `/tasks/collect` はレガシー/ローカル用途。
8) Weekly Insights / Public Facts は GitHub Actions で生成し `frontend/content/*` にコミットする（Next.js は fs で読む）。
9) 秘密値は環境変数のみ。`NEXT_PUBLIC_*` に秘密を入れない。
10) `blog_drafts` への保存は **Next.js API routes（サーバー）** からのみ行い、`SUPABASE_SERVICE_ROLE_KEY` はサーバー環境変数に限定する。ブラウザから Supabase を直接叩かない（従来のレイヤ方針と整合）。
11) **ブログ / LINE 配管に n8n は使わない**。Webhook 司令塔は Next.js（`POST /api/line`）のみ。

## やらないこと（ハードルール）
- `/api/range` にクエリ追加・サーバ側の夜窓フィルタ追加。
- **Flask / Next の proxy 層で**「夜窓だけ返す」などの時間フィルタを入れる（**取得後のクライアント／サーバーアプリ層での集計は可**）。
- Places API / DB 保存を二次会スポットの本流に戻す。
- フロントから Supabase 直アクセス。
- secrets のハードコード。
- **n8n に依存した** LINE 受付・ジョブキュー・本番配管。
