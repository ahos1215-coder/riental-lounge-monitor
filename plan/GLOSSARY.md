# GLOSSARY
Last updated: 2026-07-11（店舗数・schema_version・LightGBM表記を実コードに合わせて修正 — Batch B3。夜窓ズレ解消・sapporo_ag閉店に伴う店舗数42（37+5）反映 — Batch G）。
2026-07-18: weekly `index.json` 廃止（別バッチ）の反映（Fable監査docs修正）

| 用語 | 意味（このリポジトリ） |
|------|------------------------|
| **夜窓（night window）** | JST で 当日 19:00〜翌 05:00 前後の来店ピーク想定帯。**Flask `/api/range` では切らない**。店舗 UI は `useStorePreviewData.ts`、LINE 下書きは `insightFromRange.ts`。夜セッションの日付境界は「-6h シフト」（`oriental/ml/night_type.py` の `NIGHT_SESSION_SHIFT_HOURS=6`。00:00-05:59 は前夜扱い）で単一ソース化されている。`scripts/generate_weekly_insights.py` の独自 `hour < 5` との1時間ズレは **2026-07-11 に解消済み**（`_night_date` は `night_type.py` の `NIGHT_SESSION_SHIFT_HOURS` を参照）。 |
| **`src_brand`** | Supabase `logs` テーブルのブランド識別カラム。`'oriental'`（Oriental Lounge + ag、計37店舗。**2026-07-11 sapporo_ag閉店により38→37**）/ `'aisekiya'`（相席屋、**5店舗**、2026-04-17〜。旧6店舗から `ay_niigata` 廃止で5店舗に減）。 |
| **`brand`（StoreMeta）** | `frontend/src/data/stores.json` の店舗ブランド属性。`"oriental"` / `"aisekiya"` / `"jis"`（未実装）。`config/stores.ts` で型定義。 |
| **店舗数の正本** | 店舗数は `oriental/utils/stores.py` の `ALL_STORE_IDS`（= `STORE_IDS` 37 + `AISEKIYA_STORE_IDS` 5 = **42**）を正とする。`frontend/src/data/stores.json` の行数（42）と一致必須。**2026-07-11 sapporo_ag閉店により42店（37+5）** — 旧「43店（38+5）」表記は誤りになった。plan 配下に残る「38店舗」「44店舗」という総数表記は誤り（オリエンタル単体を指す文脈での「37」が現行正しい値）。 |
| **schema_version** | ML モデルの特徴量スキーマバージョン。**v7 (2026-07〜)** が現行（`oriental/config.py` の既定値、`.env.example`）。特徴量は24列（`preprocess.py` の `FEATURE_COLUMNS`。v6 と同じ24列）。v7は列追加ではなく `total_slope_30min` のターゲットリーク修正（v6モデルと非互換・再学習必須）。GitHub Actions Repository Variable `FORECAST_MODEL_SCHEMA_VERSION` と Render 環境変数を同じ値に揃えないと `model_registry.py` が mismatch で予測停止する（`plan/DECISIONS.md` 44番）。 |
| **LightGBM** | 推論モデルの実装。XGBoost から 2026-04-12 に移行。メモリフットプリント約半分、学習時間 5 分。**ファイル名は `model_xgb.py` のまま**（import 互換のため改名禁止）で、中身は LightGBM 優先ロード + XGBoost フォールバック。 |
| **逆算ロジック（相席屋）** | 相席屋は人数ではなくパーセンテージ表示のため、`(座席数+VIP)×2 × %` で推定人数を逆算。`AISEKIYA_STORES` dict に座席数マスタを保持。**「※推計値」と免責ページに明記**。 |
| **`avoid_time`** | 内部キー名は歴史的経緯で `avoid_time`。実体は窓内で `total` が**最も小さい**時間帯。**記事には一切使わない**（開店直後は食事目的・出勤前層が含まれ、相席の質とは無関係なため。`draftGenerator.ts` のプロンプトで明示的に禁止）。記事で出力するのは `peak_time` と `crowd_label` のみ。 |
| **`blog_drafts`** | Supabase テーブル。Daily / Weekly / Editorial の 3種類すべてを保存。`content_type` / `is_published` / `edition` / `public_slug` で分類・管理。 |
| **`content_type`** | `blog_drafts` の分類カラム。`'daily'`（定時 AI 予測）/ `'weekly'`（週次 AI 週報）/ `'editorial'`（LINE 指示による分析ブログ）のいずれか。 |
| **`is_published`** | `blog_drafts` の公開フラグ。`daily` / `weekly` は生成完了時に `true`（自動）。`editorial` は LINE 承認後に `true`。 |
| **`edition`** | Daily の便名（`evening_preview` = 18:00 JST 便 / `late_update` = 21:30 JST 便）または `'weekly'`。 |
| **`public_slug`** | Editorial のアクセスパス。`/blog/[slug]` に使用。UNIQUE 制約（null 以外）。 |
| **`facts_id`** | `blog_drafts` の論理 ID。Daily は `auto_<store>_<edition>`、Weekly は `weekly_<store>`。UNIQUE 制約。 |
| **Daily Report** | `content_type='daily'` のコンテンツ。**2026-07〜、毎日 18:00 / 21:30 にオーナーPCのローカル Ollama（`local_report_job.py`、Task Scheduler `MEGRIBI-daily-evening`/`-late`）が自動生成・即時公開**。GHA `trigger-blog-cron.yml` は同時刻の schedule をコメントアウト済みで `workflow_dispatch`（緊急用）のみ。URL は `/reports/daily/[store_slug]`（固定 URL 上書き）。詳細は `docs/LOCAL_LLM_SETUP.md`。 |
| **Weekly Report** | `content_type='weekly'` のコンテンツ。**2026-07〜、毎週水曜 06:30 JST にオーナーPCのローカル Ollama（`generate_weekly_insights.py --stores all`、Task Scheduler `MEGRIBI-weekly`）が全42店舗を自動生成・即時公開**。GHA `generate-weekly-insights.yml` は schedule をコメントアウト済みで `workflow_dispatch`（緊急用、37店舗＝オリエンタルのみの matrix）のみ。URL は `/reports/weekly/[store_slug]`（固定 URL 上書き）。 |
| **Editorial Blog** | `content_type='editorial'` のコンテンツ。LINE 指示 → AI 下書き → LINE 承認で公開。URL は `/blog/[public_slug]`。 |
| **Fan-in Matrix** | Weekly Report の GHA 手動実行（緊急用）の構成。Fan-out（オリエンタル37店舗並列）→ Fan-in（Artifact 集約・Git commit 1回）。通常運用のローカル生成はこの構成を使わず単一プロセスで全42店舗を順次処理する。**Fan-in が再構築していた `index.json` は読み手（フロントエンド）が存在しない死蔵ファイルと判明し、別バッチ（weekly-cleanup）で廃止中**。 |
| **`--skip-index`** | `generate_weekly_insights.py` のフラグ。Fan-in の各 matrix ジョブで `index.json` 書き込みを抑制するために使用。**`index.json` 自体の廃止（weekly-cleanup バッチ）に伴い、このフラグと Fan-in 側の再構築ステップも用途を失い順次整理される見込み**。 |
| **`RANGE_LIMIT`** | `LINE_RANGE_LIMIT`（LINE 経路、既定 500）/ `BLOG_CRON_RANGE_LIMIT`（定時 Cron、既定 500）。小さいとインサイトが偏る。 |
| **n8n** | **ブログ/LINE 配管には使わない**（廃止方針）。 |
| **正本（source of truth）** | 混雑ログは Supabase `logs`。コンテンツ（下書き）は Supabase `blog_drafts`。Weekly JSON ファイルは GitHub。 |
