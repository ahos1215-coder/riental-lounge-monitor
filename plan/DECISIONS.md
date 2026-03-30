# DECISIONS
Last updated: 2026-03-30 (Round 8.5 整合)
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
12) **LINE 下書き**が Flask `/api/range` を呼ぶときの `limit` は **`LINE_RANGE_LIMIT`**（既定 **500**、上限 50000）。旧 20 行固定はインサイトが偏るため廃止。**定時 Cron** は **`BLOG_CRON_RANGE_LIMIT`**（既定 500）で別管理。必要なら両方同じ値に揃える。
13) **`/api/current`** は当面、**Flask 実装どおり（ローカルキャッシュの最新など）**を維持する。Supabase 直取得へ寄せる場合は **別タスク**（契約・キャッシュ・メタ API の整合が必要）。**補足の全文**は **`plan/API_CURRENT.md`**。
14) **`POST /api/line` のレート制限**: Webhook は **エンドユーザー IP ではなく LINE サーバー経由**のため、**クライアント IP を正本の制限キーにしない**。署名検証成功後に **グローバル（分あたり）** と、高コストな `runBlogDraftPipeline` を **LINE `userId` あたり（時間あたり）**で制限する。分散環境では **Upstash Redis**（`UPSTASH_REDIS_REST_*`）を推奨。全体超過時は **200 OK で処理スキップ**（再送増とコスト抑制）、ユーザー超過時は **返信文で案内**。
15) **`SKIP_LINE_SIGNATURE_VERIFY`**: **`NODE_ENV=development` かつ値が `"1"` のときのみ** `x-line-signature` 検証をスキップする。本番・Preview では **無効**（誤設定でも署名必須）。ローカル検証は `npm run dev` 前提（`plan/ENV.md`）。
16) **コンテンツの 3 分類（`blog_drafts.content_type`）**:
    - `daily`（毎日 GHA 自動生成）/ `weekly`（毎週水曜 GHA 自動生成）/ `editorial`（LINE 指示 + 人間承認）の 3種類のみ許容。
    - `daily` / `weekly` は生成完了時に `is_published=true`（承認不要）。`editorial` は生成時 `is_published=false`、LINE 承認で `true`。
    - URL は `daily` → `/reports/daily/[store_slug]`、`weekly` → `/reports/weekly/[store_slug]`、`editorial` → `/blog/[public_slug]`。
    - **旧 `/blog/auto-[store]-[slot]` URL は廃止**（`sitemap.ts` からも除去済み）。
17) **Weekly Report の Fan-in Matrix**:
    - `generate-weekly-insights.yml` は Fan-out（38店舗並列、`max-parallel: 10`）＋ Fan-in（index.json 一元マージ、Git commit 1回）構成を維持する。
    - 各 matrix ジョブは `--skip-index` で `index.json` 書き込みを行わない（競合防止）。
    - Supabase への upsert は各 matrix ジョブ内で完結させる（Fan-in ジョブは Git 操作のみ）。
18) **Daily Report の matrix**: `max-parallel: 15`（Render 負荷上限として維持。504 多発時は下げる）。

## やらないこと（ハードルール）
- `/api/range` にクエリ追加・サーバ側の夜窓フィルタ追加。
- **Flask / Next の proxy 層で**「夜窓だけ返す」などの時間フィルタを入れる（**取得後のクライアント／サーバーアプリ層での集計は可**）。
- Places API / DB 保存を二次会スポットの本流に戻す。
- フロントから Supabase 直アクセス。
- secrets のハードコード。
- **n8n に依存した** LINE 受付・ジョブキュー・本番配管。

## ML decisions (keep)
19) **ML schema_version**: 特徴量変更時は `schema_version` をバンプし、Flask / GHA / `.env.example` のデフォルトを同時に更新する。`model_registry.py` が不一致時に 503 を返す設計を維持。
20) **FEATURE_COLUMNS**: 推論時に NaN やメジアン充填になる特徴量（ラグ/MA 系等）は `FEATURE_COLUMNS` から除外する。学習中間計算で使う特徴量は `add_time_features()` で生成するが、モデル入力には含めない。
21) **Train/Test Split**: 時系列データのため **ランダム分割は禁止**。常に時系列順（古い方が Train、新しい方が Test）で分割する。
22) **本番モデルの学習**: Holdout Test で最適な `n_estimators` を発見した後、**全データで再学習して本番モデルとする**（Early Stopping は評価用のみ）。
23) **推論時利用可能な特徴量のみ追加**: 新しい特徴量は「推論時に 7 日分の history から算出可能」であることが必須条件。`same_dow_last_week_total`（v3）はこの基準を満たす。
