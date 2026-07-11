CLAUDE.md — MEGRIBI（Oriental Lounge Monitor）3分マップ
最終更新: 2026-07-11（Batch B3: 新規作成。全ての記述は実コードを確認して書いた。詳細な根拠・過去の設計判断は plan/*.md を参照。
Batch G: gunicorn `--graceful-timeout 30` を Procfile 実物に合わせて追記 + sapporo_ag閉店で店舗数42（37+5）に更新）

このファイルは「初めてこのリポジトリを開いた AI が3分で全体像を掴み、古いドキュメントに
騙されないようにする」ためのものです。plan/ 配下の各ファイルより新しく、迷ったときは
このファイルの記述を優先してください（それでも食い違いを見つけたら、最終的にはコードが正）。

---

## 1. システム地図

```
利用者ブラウザ
  └─ Next.js 16 / React 19（frontend/、Vercel Free、GitHub連携でmain push→自動デプロイ）
       └─ BACKEND_URL 経由で Flask API を呼ぶ（ブラウザから Supabase 直叩きはしない）
            └─ Flask（oriental/、Render Starter $7/月。エントリポイントは wsgi:app）
                 ├─ Supabase Postgres（logs / blog_drafts 等）— データの正本
                 ├─ Supabase Storage bucket "ml-models"（学習済みモデル + 精度追跡JSON）
                 └─ Google Sheet / GAS（レガシー fallback。通常経路では使わない）

定時バッチ（.github/workflows/ 21本 + オーナーPCの Task Scheduler）
  ├─ 収集: cron-job.org（5分毎）→ /tasks/multi_collect → multi_collect.py → Supabase logs
  ├─ Daily/Weekly Report: 【主】ローカル Ollama（オーナーPC常時稼働）
  │                        【緊急時のみ】GHA workflow_dispatch + Gemini
  ├─ ML学習・精度追跡・CDN warming 等: GHA が主（詳細は §2）
  └─ トップレベル scripts/ 配下の Python が各バッチの実体
```

- **フロント**: `frontend/src/app/`（App Router）。ページは `/`, `/stores`, `/store/[id]`,
  `/compare`, `/area/[area]`, `/reports`, `/reports/daily|weekly/[store_slug]`, `/blog`,
  `/blog/[slug]`, `/mypage` 等。
- **バックエンド**: `oriental/`（Flask アプリファクトリ）。`wsgi.py` が `oriental.create_app()` を
  呼ぶだけの薄いエントリポイント。`Procfile`: `gunicorn wsgi:app --timeout 300 --graceful-timeout 30
  --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-4}`（`--preload` は意図的に
  未使用。fork-after-thread hazard を避けるため）。
- **収集スクリプト**: リポジトリ直下の `multi_collect.py`（`STORES` / `AISEKIYA_STORES` /
  `PREF_COORDS` を定義。`oriental/routes/tasks.py` が import して使う）。
- **バッチスクリプト**: `scripts/` 配下（ML学習・ローカルレポート生成・CDN warming・v2 shadow評価
  など。一覧は `plan/ARCHITECTURE.md` の Key Files 参照）。
- **店舗数は 42**（オリエンタル37 + 相席屋5）。**2026-07-11 sapporo_ag閉店により43（38+5）から
  42（37+5）に変更**。オリエンタルには韓国・ソウルの `ol_gangnam` を含む。
  正本は `oriental/utils/stores.py` の `ALL_STORE_IDS`（= `STORE_IDS`37 + `AISEKIYA_STORE_IDS`5）と
  `frontend/src/data/stores.json`（行数が一致必須）。plan/ 配下に残る「38店舗」「43店舗」「44店舗」
  という**総数**表記は誤り（オリエンタル単体の文脈での「37」が現行正しい値）。

### コンテンツの3分類（`blog_drafts.content_type`）

| 種類 | URL | 生成元（主経路） | 公開フラグ |
|---|---|---|---|
| `daily` | `/reports/daily/[store_slug]` | ローカル Ollama（毎日18:00/21:30） | 生成完了時に自動 `true` |
| `weekly` | `/reports/weekly/[store_slug]` | ローカル Ollama（毎週水曜06:30） | 生成完了時に自動 `true` |
| `editorial` | `/blog/[public_slug]` | LINE指示 → Vercel `POST /api/line` → Gemini下書き | 最初は`false`、LINE承認で`true` |

`daily`/`weekly`は同一`store_slug`に対し**最新行を上書き**（固定URL、Freshness優先）。`editorial`のみ
ユニークURL。3分類とも失敗時は本文空・`is_published=false`・`error_message`ありの2状態を厳守する。

### 環境変数（迷ったときに真っ先に見るもの）

`BACKEND_URL`（フロント→Flask）／`CRON_SECRET`（`/tasks/*`のBearer認証）／`SUPABASE_URL`+
`SUPABASE_SERVICE_ROLE_KEY`（Next.jsサーバー側のみで使用、ブラウザからは直叩きしない）／
`FORECAST_MODEL_BUCKET`(既定`ml-models`)+`FORECAST_MODEL_PREFIX`(既定`forecast/latest`)+
`FORECAST_MODEL_SCHEMA_VERSION`(既定`v7`)／`ENABLE_FORECAST`／`GEMINI_API_KEY`（Editorial・GHA緊急時用）。
全量は `plan/ENV.md`。

---

## 2. データフロー（時系列）

| 時刻(JST) | 何が起きるか | 主体 |
|---|---|---|
| 5分毎 | 混雑データ収集 | cron-job.org → `/tasks/multi_collect`（`CRON_SECRET`認証）→ `collect_all_once()` → Supabase `logs`。オリエンタル・相席屋それぞれのトップページSSRから2リクエストで全42店舗分を取得 |
| 18:00 / 21:30 | **Daily Report生成** | 【主】Task Scheduler `MEGRIBI-daily-evening`/`-late` → `scripts/local_report_job.py --stores all --edition <evening_preview\|late_update> --mode publish` → ローカル Ollama（`gemma4:e4b`、`localhost:11434`）→ Supabase `blog_drafts` upsert。【緊急時のみ】`.github/workflows/trigger-blog-cron.yml` は `schedule:` コメントアウト済み、`workflow_dispatch`のみ（matrixはオリエンタル37店舗、相席屋5店舗は対象外、Gemini使用） |
| 18:10 | v2 shadow: 予測スナップショット保存 | GHA `forecast-accuracy-track.yml`（mode=snapshot）→ `scripts/snapshot_forecasts.py` → Storage `ml-models/accuracy/snapshots/<date>.json` |
| 19:00〜23:50・10分毎 | CDN warming（`/api/range`等の温め） | 【主】Task Scheduler `MEGRIBI-warm-cdn` → `scripts/warm_cdn_local.py`。【バックアップ】GHA `warm-cdn.yml`（実測発火率8.3%と低いため保険止まり） |
| 水曜 06:30 | **Weekly Report生成** | 【主】Task Scheduler `MEGRIBI-weekly` → `run_weekly_local.ps1 -Stores all` → `generate_weekly_insights.py --stores all`（`INSIGHTS_LLM_BACKEND=ollama`）が全42店舗を単一プロセスで処理 → Supabase upsert + `frontend/content/insights/weekly/*.json` + `index.json` 直接更新。【緊急時のみ】`generate-weekly-insights.yml`（`workflow_dispatch`, Fan-in Matrix, オリエンタル37店舗のみ, Gemini使用） |
| 05:30 毎日 | ML再学習（固定パラメータ） | GHA `train-ml-model.yml` → `scripts/train_ml_model.py`。`ALL_STORE_IDS`（42店舗）allow-listでLightGBM学習 → Storage `ml-models/forecast/latest/` |
| 07:00 月曜 | ML再学習 + Optuna HPO | 同じ `train-ml-model.yml`（cronパターンで分岐。日次はOptunaなし、週次のみHPOあり） |
| 06:10 | v2 shadow: 前夜の答え合わせ | GHA `forecast-accuracy-track.yml`（mode=score）→ `scripts/score_forecasts.py` → Storage `ml-models/accuracy/scores/<date>.json` + `summary.json` |
| 07:30 | v2 shadow: テンプレ再生成 | GHA `build-templates.yml` → `scripts/build_templates.py` → Storage `forecast/templates_v2.json` |
| 09:30 | Public Facts生成 | GHA `generate-public-facts.yml` → `frontend/content/facts/public/*.json` → git commit |

**重要**: v2 shadow パイプライン（18:10 snapshot / 06:10 score / 07:30 templates）は**答え合わせ・評価専用**で、
本番配信 (`oriental/ml/forecast_service.py`) には一切影響しない。「v2」という名前に惑わされて
本番予測ロジックだと誤解しないこと（`build-templates.yml` 自身のコメントに明記あり）。

**ローカルとGHAの二重生成に注意**: Daily/Weekly は同じ `facts_id` / `blog_drafts` 行を奪い合うため、
ローカルジョブが動いている時間帯にGHA `workflow_dispatch` を手動実行しないこと。

---

## 3. 絶対不変リスト（変更前に一度立ち止まること）

- **エントリポイント**: `wsgi:app`（`wsgi.py` → `oriental.create_app()`）。`multi_collect.py`
  トップレベル + `/tasks/multi_collect`（`oriental/routes/tasks.py`）。
- **`/api/range` の契約**: `store` + `limit` のみ。サーバー側の時間フィルタは禁止（夜窓判定は
  フロント `useStorePreviewData.ts` / LINE用 `insightFromRange.ts` の役割）。
- **API 一式**: `/healthz`, `/api/meta`, `/api/current`, `/api/range`, `/api/range_multi`,
  `/api/forecast_*`, `/api/forecast_today_multi`, `/api/megribi_score`, `/api/forecast_accuracy`,
  `/api/holiday_status`, `/tasks/*`。既存互換性を維持すること。
- **Storage レイアウト**（bucket既定値 `ml-models`）: `forecast/latest/*`（モデル本体+`metadata.json`、
  `schema_version`必須一致）/ `accuracy/snapshots/*.json`・`accuracy/scores/*.json`・
  `accuracy/scores/summary.json`・`accuracy/blend_weights.json`（v2 shadow）/ `forecast/templates_v2.json`。
- **フロントの動的ルート**: `/store/[id]`, `/reports/daily/[store_slug]`,
  `/reports/weekly/[store_slug]`, `/blog/[slug]`, `/area/[area]`。
- **店舗マスタの単一ソース**: `oriental/utils/stores.py::ALL_STORE_IDS`（Python側の店舗解決・ML
  allow-list）と `frontend/src/data/stores.json`（Frontend & 収集スクリプト共通）。行数は常に一致。
- **やらないと決めていること**: n8n（LINE/ブログ配管に不使用）／Vercel Cron（`vercel.json`削除済み、
  二重実行防止）／二次会の Places API 化（map-link方式を維持）。

---

## 4. よくある罠（AIが引っかかりやすいポイント）

1. **`oriental/ml/model_xgb.py` の中身は LightGBM。** 2026-04-12 に移行済みで、ファイル名は import
   互換のためだけに残っている。「XGBoost」という名前・変数名に引きずられて古い前提でコードを
   書かないこと。**改名しないこと**（多数のimport箇所が壊れる）。
2. **夜セッションの日付境界のズレは2026-07-11に解消済み（もう罠ではない）**: 旧
   `scripts/generate_weekly_insights.py` は独自に `hour < 5` で丸めており、`oriental/ml/postprocess.py` /
   `night_type.py` の `NIGHT_SESSION_SHIFT_HOURS=6`（00:00-05:59は前夜扱い、「-6hシフト」規約）と
   1時間ずれていた。3店舗（shibuya/ay_chiba/takasaki）の本番 `/api/range` 実データで検証したところ
   直近7日間 JST 5時台（収集は ~04:55 JST で停止）の行は0件で、hour<5→hour<6 の統一による
   nightly件数・daily_summary・heatmap集計への実影響はゼロだったため、`night_type.py` の
   `NIGHT_SESSION_SHIFT_HOURS` を単一ソースとする `hour < 6` に統一した
   （`_night_date` は now `from oriental.ml.night_type import NIGHT_SESSION_SHIFT_HOURS` を参照）。
   履歴として記録: 統一前は「意図的に放置」と判断されていたが、実データ検証により解消した。
3. **相席屋は%表示のみ。人数はバックエンド内部の逆算推定値**（`(座席数+VIP)×2 × %`）で、
   UIには表示しない（「※推計値」を免責ページに明記する方針）。
4. **`frontend/src/data/stores.json` が店舗マスタの唯一の正本。** 店舗の追加・削除はこのファイルと
   `oriental/utils/stores.py`（Python側）の両方に影響する。片方だけ直すと店舗数不整合になる。
5. **GHAの`schedule:`は間引かれる（信用しすぎない）。** CDN warmingで実測したところ、10分毎・
   19:00-23:50想定の60回に対し実際の発火は5回（8.3%）だった。これが「主経路をローカルPCの
   Task Schedulerへ移す」という判断の直接的な根拠になった。ワークフローのコメントに
   「動くはず」と書いてあっても、実際にどちらが主経路かは `docs/LOCAL_LLM_SETUP.md` /
   `plan/CDN_WARMING_LOCAL.md` で確認すること。
6. **`docs/LOCAL_LLM_SETUP.md` 本文はまだ `gemma4:12b` と書いているが、実際の本番モデルは
   2026-07-08に `gemma4:e4b` へ変更済み**（`scripts/local_report_job.py` の `MODEL` 定数、
   `scripts/experiments/local_llm_spike.py` 参照）。ドキュメント自体が古いことがあるので、
   モデル名などピンポイントな値は最終的にコードで確認すること。
7. **`schema_version` は3箇所同期が必要**: `oriental/config.py` の既定値 / GHA Repository Variable
   `FORECAST_MODEL_SCHEMA_VERSION` / Render 環境変数。ズレると `model_registry.py` が
   `schema_version mismatch` で予測を停止する（現行値は `v7`、24特徴量）。
8. **PowerShellでは `&&` / `||` が使えない**（Windows PowerShell 5.1）。`A; if ($?) { B }` を使う。
   Bashツールでコマンドを打つ場合は POSIX sh なので `&&` は普通に使える。
9. **Windowsコンソールの既定コードページは cp932。** Python スクリプトが日本語を `print` すると
   `UnicodeEncodeError` になり得る（`scripts/local_report_job.py` は ASCII エスケープで回避済み）。
   対話的にコマンドを実行する場合は `$env:PYTHONUTF8=1` を設定するか `python -X utf8` を使うと安全。
10. **ML学習は日次（05:30・Optunaなし）と週次（月曜07:00・Optuna HPOあり）の2スケジュールが
    同じ `train-ml-model.yml` に同居している。** 「日次学習」とだけ書いてある古い記述を見ても、
    週次のOptuna実行を見落とさないこと。

---

## 5. 深掘りリンク

- `plan/ARCHITECTURE.md` — データフロー全量・並列化パターン・Key Files一覧（本ファイルより詳細）
- `docs/LOCAL_LLM_SETUP.md` — ローカルLLMレポート生成のセットアップ・復旧手順（正本）
- `plan/BLOG_CRON_GHA.md` — GHA緊急時手順・Secrets一覧（通常運用の正本ではない点に注意）
- `plan/RUNBOOK.md` — 起動手順・定期処理一覧・トラブルシュート
- `plan/GLOSSARY.md` — 用語集（夜窓、`src_brand`、schema_versionほか）
- `plan/DECISIONS.md` — 壊してはいけない過去の判断
- `plan/README.md` — `plan/` フォルダ全体のナビ・推奨読了順
- `plan/FORECAST_V2.md` / `plan/FORECAST_ACCURACY.md` — v2 shadow パイプラインの設計・答え合わせ運用
- `plan/CDN_WARMING_LOCAL.md` — CDN warmingのローカル移行の経緯・Task Scheduler登録手順

---

## 6. 開発・テスト

```bash
python -m pytest -q         # pytest.ini: testpaths=tests, pythonpath=.
```

```powershell
cd frontend; npm run dev    # Next.js（frontendディレクトリ内で実行。二重cdに注意）
python app.py                # Flask ローカル起動（.env に環境変数、plan/ENV.md参照）
```

このファイルの記述と実際のコードが食い違っていたら、コードを信じて `CLAUDE.md` を更新してください。
