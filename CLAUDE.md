CLAUDE.md — MEGRIBI（Oriental Lounge Monitor）3分マップ
最終更新: 2026-09-26（§4罠11に Supabase の次の壁2つ＝ログ取り込み枠 月1GB（2027年初めから）と DB 容量 500MB を追記。
収集の Supabase 書き込みを1店ずつ→まとめて1回に変更した反映）。
2026-09-18（§4罠5の GHA `schedule:` 発火率を 2026-09-18 の実測で書き換え＝毎時24%・2時間毎43〜65%・
6時間毎96%・日次100%だが1.5〜5時間遅れ。「毎時」も間引かれる側で、監視の頻度設計は日次を基準にする。
§4に罠12「LINE 通知は Secrets 未設定だと黙って no-op になる」を追加＝2026-09-18 時点で全 LINE 経路が届いていなかった）。
2026-09-09（§4に罠11「Supabase無料プランの枠が実運用の制約になっている」を追加＋
§5に障害記録2本へのリンクを追加。2026-09-05の全停止を受けたもの）。
2026-07-11（Batch B3: 新規作成。全ての記述は実コードを確認して書いた。詳細な根拠・過去の設計判断は plan/*.md を参照。
Batch G: gunicorn `--graceful-timeout 30` を Procfile 実物に合わせて追記 + sapporo_ag閉店で店舗数42（37+5）に更新）。
2026-07-18: weekly `index.json` 廃止（別バッチ）の反映 + コメント/ENV.md/e2e/依存関係の修正（Fable監査分）
2026-08-21: 外部レビュー(ChatGPT/Codex)第1〜2ラウンドの指摘15件のうち12件を修正した反映
（/api/* のレート制限・/api/range の総行数上限・スナップショット昇格ガード・監視の全店必須化・週報のJST日付）。
2026-08-19: 大整理第3弾（Fable棚卸し59件→Sonnet反証→Opus実装・挙動不変）の反映。共通モジュール地図（§7）を新設、
`/api/range` 契約の実態合わせ、モデル名の正本の移動、vercel.json の実在、テスト規約（conftest / server-only）を追記。
2026-08-21（第3ラウンド）: §4罠5「GHAのscheduleは間引かれる」を頻度依存の記述に訂正（日次/週次cron5本は
実測30日間で発火欠落ゼロ。間引きは10分毎などの高頻度cron固有）。

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

定時バッチ（.github/workflows/ 23本・うち schedule 持ち13本 + オーナーPCの Task Scheduler）
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
  呼ぶだけの薄いエントリポイント。`Procfile`: `env MALLOC_ARENA_MAX=2 gunicorn wsgi:app --timeout 300
  --graceful-timeout 30 --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-8}
  --max-requests 6000 --max-requests-jitter 200`（2026-07-17 メモリ事件#2で workers 2→1 / threads 4→8。
  2026-08-21 第3ラウンドで `--max-requests` を 1500→6000 に引き上げ:
  gunicorn は WSGI 呼び出し**前**にカウンタを進めるため `/api/*` レート制限の429もここに乗り、
  429連打だけで再生成（＝レート制限の記憶とモデルpreloadのやり直し）が速く到達していた
  （詳細・根拠は `Procfile` 本文コメント）。
  `--preload` は意図的に未使用。fork-after-thread hazard を避けるため）。
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
ユニークURL。失敗時の状態は**carry-over方式**（2026-07-18・Fable監査B2で日次も週次に合わせた）:
①成功＝本文+`is_published=true`。②失敗かつ**過去に公開済みの良品がある**＝前回の本文/公開フラグ/
**`target_date`を保持**し、`error_message`は**null のまま**（フロントは`is_published=true`かつ
`error_message is null`で表示行を絞るため、ここに理由を書くと読者に届かなくなる。失敗理由は
`insight_json.last_error`とログへ。2026-08-19・所見1）。③失敗かつ良品が一度も無い新規店＝本文空・
`is_published=false`・`error_message`あり。`editorial`は最初false→LINE承認でtrue。

### 環境変数（迷ったときに真っ先に見るもの）

`BACKEND_URL`（フロント→Flask）／`CRON_SECRET`（`/tasks/*`のBearer認証）／`SUPABASE_URL`+
`SUPABASE_SERVICE_ROLE_KEY`（Next.jsサーバー側のみで使用、ブラウザからは直叩きしない）／
`FORECAST_MODEL_BUCKET`(既定`ml-models`)+`FORECAST_MODEL_PREFIX`(既定`forecast/latest`)+
`FORECAST_MODEL_SCHEMA_VERSION`(既定`v7`)／`ENABLE_FORECAST`／`GEMINI_API_KEY`（Editorial・GHA緊急時用）。
`BLEND_WEIGHTS_MODE`(既定`frozen`。2026-08-22に重み自動更新を凍結、`legacy_daily`は緊急用のみ)／
`API_RATE_LIMIT_PER_MIN`(既定300)+`API_RATE_LIMIT_ENABLED`(既定1。`0`で即停止＝キルスイッチ)／
`MAX_RANGE_TOTAL_ROWS`(既定12000)／`SNAPSHOT_MIN_STORES`系の昇格ガード／`STRICT_ALL_STORES`(既定1)+
`ALLOWED_MISSING_SLUGS`(監視の逃がし弁)／`DAILY_EXIT_NONZERO`(既定1)。
全量は `plan/ENV.md`。

---

## 2. データフロー（時系列）

| 時刻(JST) | 何が起きるか | 主体 |
|---|---|---|
| 5分毎 | 混雑データ収集 | cron-job.org → `/tasks/multi_collect`（`CRON_SECRET`認証）→ `collect_all_once()` → Supabase `logs`。オリエンタル・相席屋それぞれのトップページSSRから2リクエストで全42店舗分を取得。Supabase への書き込みもブランドごとに**まとめて1回**（2026-09-26〜。以前は1店ずつ。§4 罠11） |
| 18:00 / 21:30 | **Daily Report生成** | 【主】Task Scheduler `MEGRIBI-daily-evening`/`-late` → `scripts/local_report_job.py --stores all --edition <evening_preview\|late_update> --mode publish` → ローカル Ollama（`gemma4:e4b`、`localhost:11434`）→ Supabase `blog_drafts` upsert。【緊急時のみ】`.github/workflows/trigger-blog-cron.yml` は `schedule:` コメントアウト済み、`workflow_dispatch`のみ（matrixはオリエンタル37店舗、相席屋5店舗は対象外、Gemini使用） |
| 18:10 | v2 shadow: 予測スナップショット保存 | 【主】Task Scheduler `MEGRIBI-snapshot` → `scripts/snapshot_forecasts.py` → Storage `ml-models/accuracy/snapshots/<date>.json`。GHA `forecast-accuracy-track.yml` の snapshot cron は 2026-07-18 に削除済み（GHA schedule の遅延で開店後に撮れて汚染したため。`workflow_dispatch` は残る） |
| 19:00〜23:50・10分毎 | CDN warming（`/api/range`等の温め） | 【主】Task Scheduler `MEGRIBI-warm-cdn` → `scripts/warm_cdn_local.py`。【バックアップ】GHA `warm-cdn.yml`（実測発火率 15〜34%（2026-08）と低いため保険止まり。§4 罠5） |
| 水曜 06:30 | **Weekly Report生成** | 【主】Task Scheduler `MEGRIBI-weekly` → `run_weekly_local.ps1 -Stores all` → `generate_weekly_insights.py --stores all`（`INSIGHTS_LLM_BACKEND=ollama`）が全42店舗を単一プロセスで処理 → Supabase upsert + `frontend/content/insights/weekly/*.json`。**`index.json` は 2026-07-18 に廃止済み**（読み手が存在しない死蔵ファイルだった。`--skip-index` 引数は互換のため受けるだけの no-op）。【緊急時のみ】`generate-weekly-insights.yml`（`workflow_dispatch`, Fan-in Matrix, オリエンタル37店舗のみ, Gemini使用） |
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
- **`/api/range` の契約**: 必須は `store` + `limit`。任意で `from`/`to`（YYYY-MM-DD・日付粒度）を受け、
  片方だけならその1日。**時刻粒度のサーバー側フィルタは禁止**（夜窓判定はフロント `useStorePreviewData.ts` /
  LINE用 `insightFromRange.ts` の役割）。マルチ店舗の `stores=` 解釈は `utils/stores.parse_store_slugs`
  （小文字化→既知のみ→重複除去→上限）に一本化（range_multi / forecast_today_multi / megribi_score 共通）。
- **`/api/*` のレート制限**（2026-08-21・外部レビューF4）: Flask 側にプロセス内レート制限がある
  （既定 `API_RATE_LIMIT_PER_MIN=300`/分・IP単位、超過時 429）。**対象は `/api/*` のみ**で、
  `/healthz` `/readyz` `/tasks/*` `/api/tasks/*` `/static/*` は**必ず除外**（収集・監視を止めないため）。
  障害時は `API_RATE_LIMIT_ENABLED=0` で即無効化できる。`/api/range` は
  `len(stores) * limit > MAX_RANGE_TOTAL_ROWS`(既定12000) で 422 `range-request-too-large`。
- **壊れた成果物を正規パスへ昇格させない**（2026-08-21・外部レビューF1）: `scripts/snapshot_forecasts.py` は
  規定数に満たない夜は `accuracy/snapshots/<date>.json` を**上書きせず非ゼロ終了**する。
  `scripts/score_forecasts.py` はスナップショット不在を「no snapshot found」でアラート＋exit 1。
  **嘘の精度を出さない代わりに、欠落した夜は精度が空欄になる**のが正しい挙動（空欄を「バグ」と誤認しないこと）。
- **監視は既定で全42店必須**（2026-08-21・外部レビューF8）: `scripts/monitor/check_daily_published.py` /
  `check_weekly_published.py` は `STRICT_ALL_STORES=1`（既定）で期待店舗集合との差分を見る。
  WF 入力 `min_published`/`min_stores` は**下限フロアに過ぎない**。緩めるときだけ
  `ALLOWED_MISSING_SLUGS=<slug,slug>` か `STRICT_ALL_STORES=0` を使う（緊急時のGHA日次はオリエンタル37店のみ
  対象なので、その日は相席屋5店を `ALLOWED_MISSING_SLUGS` に入れる）。
- **API 一式**: `/healthz`, `/api/meta`, `/api/current`, `/api/range`, `/api/range_multi`,
  `/api/forecast_*`, `/api/forecast_today_multi`, `/api/megribi_score`, `/api/forecast_accuracy`,
  `/api/holiday_status`, `/tasks/*`。既存互換性を維持すること。
- **Storage レイアウト**（bucket既定値 `ml-models`）: `forecast/latest/*`（モデル本体+`metadata.json`、
  `schema_version`必須一致）/ `accuracy/snapshots/*.json`・`accuracy/scores/*.json`・
  `accuracy/scores/summary.json`・`accuracy/blend_weights.json`（**2026-08-22に凍結**。書き手は
  `BLEND_WEIGHTS_MODE=frozen`（既定）では一切書かず、旧計算は `accuracy/blend_weights_shadow/legacy.json` へ、
  凍結時点の同一バイト列は `accuracy/blend_weights_freeze/generations/<sha256>.json` + `current.json`(manifest) へ。
  hash不変は `check-blend-weights-freeze.yml`（6時間毎）が監視。解除の設計は
  `plan/FORECAST_FREEZE_DEBATE_FINDINGS.md` F-7 が正本＝週次方式へ移行するまで恒久固定しない）/ `forecast/templates_v2.json`。
- **フロントの動的ルート**: `/store/[id]`, `/reports/daily/[store_slug]`,
  `/reports/weekly/[store_slug]`, `/blog/[slug]`, `/area/[area]`。
- **店舗マスタの単一ソース**: `oriental/utils/stores.py::ALL_STORE_IDS`（Python側の店舗解決・ML
  allow-list）と `frontend/src/data/stores.json`（Frontend & 収集スクリプト共通）。行数は常に一致。
- **やらないと決めていること**: n8n（LINE/ブログ配管に不使用）／Vercel Cron（`frontend/vercel.json` は
  main 以外のビルドを止める `ignoreCommand` 専用で cron は持たない。二重実行防止）／二次会の Places API 化
  （map-link方式を維持）／`model_xgb.py` の改名／GoogleSheet fallback・GAS 送信経路・`/api/forecast_next_hour`
  `/api/second_venues` プロキシの削除（外部呼び出し・障害時挙動が変わるためオーナー判断待ち）。

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
5. **GHAの`schedule:`は頻度が上がるほど間引かれ、日次でも予定時刻から1.5〜5時間遅れる。
   監視の頻度設計は日次を基準にする。**
   （2026-09-18・公開Actions APIで直近30日を実測して再訂正。2026-08-21 の記述「間引きは10分毎などの
   高頻度cron固有」は「毎時」を安全側に数えていた誤りだった。それ以前の「GHAのscheduleは信用しすぎない」
   という頻度を区別しない一般化も、日次については誤り。この項は2回訂正されている）
   実測の発火率: **毎時 24%、2時間毎 43〜65%、6時間毎 96%、日次 100%（ただし1.5〜5時間遅れ）**。
   10分毎の `warm-cdn` は 2026-08 の実測 15〜34%（2026-09-18 の再測定対象外）。
   つまり「毎時なら確実に発火する」は成り立たない。毎時の `site-down-watch.yml` は平均4回に1回しか走らず、
   2時間毎の `check-collection-heartbeat.yml` も半分前後しか走らない。日次・週次は欠落しないが
   **時刻は当てにならない**（cron の予定時刻を「その時刻に走る」と読まないこと。実測の遅れ幅からは
   05:30 JST 予定の `train-ml-model` が 07:00〜10:30 に走り得る）。
   設計への含意: **「N分以内に気づく」を GHA の schedule に約束させない**。速さが要る監視は
   ローカル Task Scheduler か外部 cron（cron-job.org）に置き、GHA には「1日1回は必ず来る」役を任せる
   （毎朝1通のダイジェスト方式が典型。`plan/RUNBOOK.md` の監視ワークフロー一覧を参照）。
   なお GitHub 公式の仕様として、**リポジトリが60日間無活動だと `schedule:` は自動で無効化される**。
   自分で確かめ直すには公開Actions APIを叩く
   （例: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/<file>.yml/runs?per_page=100`
   を `created_at` でフィルタし、`event=schedule` の run 数を期待回数と比較する）。
   過去の判断＝CDN warmingやsnapshot保存の主経路をローカルTask Schedulerへ移したこと自体は覆さない。
   **snapshotをローカルへ移した理由は発火の"欠落"ではなく"遅延"**——GHA schedule の遅延で開店後に撮れて
   精度計測が汚染したため——で、今回の実測（日次は欠落ゼロだが1.5〜5時間遅れ）とも整合する。
   逆に「日次も欠落する」という前提で不要なローカル移管を増やさないこと（欠落するのは高頻度側、
   日次は遅延するだけ。両者を混同しないこと）。
6. **ドキュメントのピンポイントな値（モデル名等）は最終的にコードで確認すること。**
   実例: 本番モデルは2026-07-08に `gemma4:12b`→`gemma4:e4b` へ変更されたが、
   `docs/LOCAL_LLM_SETUP.md` 本文は2026-07-11まで旧名のままだった（修正済み）。**モデル名の正本は
   `scripts/_ollama_common.py` の `MODEL` 定数**（2026-08-19 に `local_report_job.py` から移動。daily/weekly
   とも同じ定数を参照し、`local_report_job.MODEL` は再エクスポート）。なお `scripts/tune_local_llm.py` の
   既定モデルと `scripts/experiments/local_llm_spike.py` の `MODELS` に残る `gemma4:12b` はベンチ比較用の
   意図的な残置であり、本番モデルの参照ではない。
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
11. **Supabase 無料プランの枠（cached egress 5GB/月・uncached egress 5GB/月・Storage 容量1GB）が
    実運用の制約になっている。** 2026-09-05 に超過して全リクエストが402になり、サイトが3日半
    誤情報を出した（経緯・復旧手順は `docs/INCIDENT_2026-09-05_SUPABASE_QUOTA.md`）。
    Supabase からのダウンロードを増やす変更（Storage の読み足し・キャッシュの撤去）は、
    転送量への影響を見積もってから入れること。
    追記（2026-09-18 監査）: 9/5 の超過で無料プランの**猶予期間を使い切った**ため、次に超えたら
    **警告なしで即402**（Supabase 公式 Billing FAQ）。次に危ないのは uncached（DB側）egress で余裕は約1.1倍。
    主犯は urllib で REST を読むスクリプトが `Accept-Encoding` を送らず非圧縮なこと（gzip で実測 6〜11倍に縮む。select する列数で変わる）。
    urllib で Supabase を読むスクリプトを書くときは gzip を要求すること。
    追記（2026-09-26）: 次の壁は2つ（管理画面の実測）。**① ログ取り込み枠 月1GB（2027年初めから適用）**＝
    Supabase は**リクエスト1回ごとにログを1件**残すので、量はリクエスト回数に比例する（実測ペース 月1.5GB前後）。
    **Supabase へ1件ずつループで書く・問い合わせる書き方をしないこと**（収集の42店1件ずつ INSERT をまとめ書きに
    直したのが最大の削減＝`multi_collect.insert_supabase_logs`）。**② DB 容量 500MB**（2026-09-26 に70%・約1.2MB/日増）＝
    無料プランは超えると read-only で収集が止まる。詳細と見込みは `docs/FAILURE_MAP.md`。
12. **LINE 通知は Secrets 未設定だと黙って no-op になる。「LINE が静か＝正常」と読まないこと。**
    2026-09-18 時点で GitHub Secrets に `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` が無く
    （失敗 run の注記 "not set. Skipping"）、オーナーPCの `.env.local` のトークンも 401 で、
    **全 LINE 経路が1本も届いていなかった**（`site-down-watch.yml` / `check-pat-expiry.yml` の push、
    `scripts/analytics_weekly_report.py` の週次ダイジェスト、`multi_collect.py` の相席屋アラート）。
    どの経路も「未設定ならスキップして exit 0」の設計なので、ジョブは緑のまま通知だけ消える。
    オーナーがトークンを再発行して4箇所（GitHub Secrets・PC の `.env.local`・Vercel・Render の環境変数）に
    入れるまで LINE 経路は全部 no-op。LINE 経路の生死は「届いた」で確かめる（月曜の週次ダイジェストが来ない／
    `site-down-watch` の run ログに "Skipping LINE notification" が出ている＝死んでいる）。
    通知の設計を書くときは、LINE を「届く前提の終着点」に置かないこと（`docs/FAILURE_MAP.md` 冒頭「現況」）。

---

## 5. 深掘りリンク

- `docs/INCIDENT_2026-09-05_SUPABASE_QUOTA.md` — 2026-09-05 の全停止（Supabase無料枠超過）の記録・復旧手順
- `docs/FAILURE_MAP.md` — 壊れ方マップ（何が止まると何が止まり、気づけるか）
- `plan/ARCHITECTURE.md` — データフロー全量・並列化パターン・Key Files一覧（本ファイルより詳細）
- `docs/LOCAL_LLM_SETUP.md` — ローカルLLMレポート生成のセットアップ・復旧手順（正本）
- `plan/BLOG_CRON_GHA.md` — GHA緊急時手順・Secrets一覧（通常運用の正本ではない点に注意）
- `plan/RUNBOOK.md` — 起動手順・定期処理一覧・トラブルシュート
- `plan/GLOSSARY.md` — 用語集（夜窓、`src_brand`、schema_versionほか）
- `plan/DECISIONS.md` — 壊してはいけない過去の判断
- `plan/README.md` — `plan/` フォルダ全体のナビ・推奨読了順
- `plan/FORECAST_V2.md` / `plan/FORECAST_ACCURACY.md` — v2 shadow パイプラインの設計・答え合わせ運用
- `plan/CDN_WARMING_LOCAL.md` — CDN warmingのローカル移行の経緯・Task Scheduler登録手順
- `docs/ANALYTICS_AGENT_RUNBOOK.md` — GA4/Search Console分析をAIエージェントが行う手順（SSOT）

---

## 6. 開発・テスト

```bash
python -m pytest -q         # pytest.ini: testpaths=tests, pythonpath=.
```

- `tests/conftest.py` が `DISABLE_MODEL_PRELOAD=1` を立てる（モデル事前ロードのスレッドがグローバル
  `time.sleep` を差し替えるテストに混入してランダムに落ちる穴を封止）。
- vitest は `server-only` を `src/test/server-only-stub.ts` に alias（サーバー専用モジュールを import する
  テストを書ける）。`next build` / `npm test` 全体は作業ツリーを共有する並列エージェントと衝突するため、
  並列作業中は各班は `npx tsc --noEmit` + `npx vitest run <file>` のみ、統括が最後にまとめて回す。
- 番犬テストの流儀: 整理の前に「旧実装の出力をフィクスチャ/スナップショットに固定」→整理→同じテストが緑。
  URL表は `tests/test_url_map_stability.py`（SHA一致）、店舗マスタは `test_store_id_ssot.py`、
  ページ metadata は `src/lib/seo/pageMetadata.snapshot.test.ts`、StoreSnapshot 組立は
  `assembleStoreSnapshot.parity.test.ts` が検問。
- `scripts/score_forecasts.py` / `snapshot_forecasts.py` は argparse を持たない＝引数を付けても本番ジョブが
  丸ごと走る。確認目的で実行しない（import / pytest で確認）。

```powershell
cd frontend; npm run dev    # Next.js（frontendディレクトリ内で実行。二重cdに注意）
python app.py                # Flask ローカル起動（.env に環境変数、plan/ENV.md参照）
```

## 7. 共通モジュール地図（同じ処理を手書きしない。ここを先に探す）

| したいこと | 使うもの |
|---|---|
| Supabase の認証ヘッダ・Storage オブジェクト取得（Flask 側） | `oriental/clients/supabase.py`（`auth_headers` / `storage_object_url` / `storage_get_bytes`） |
| 有限数判定・ts 正規化・env の float 読み（Flask/ML 側） | `oriental/ml/_num.py` |
| 店舗マスタ（ID/slug/capacity/座標）・`stores=` の解釈 | `oriental/utils/stores.py`（`ALL_STORE_IDS` / `load_stores_rows` / `parse_store_slugs`） |
| 連休ブロック・夜セッション日付（-6h） | `oriental/ml/holiday_calendar.py`（`off_block_bounds`）/ `oriental/ml/night_type.py` |
| forecast 応答の形・エラーコード | `routes/forecast.py::_success_body` / `ml/forecast_service.py::_error_result` |
| バッチ scripts の .env 読み・Supabase 認証ヘッダ/接続情報・Storage GET/PUT（REST 本体は各スクリプト） | `scripts/_supabase_common.py`（`auth_headers` / `supabase_conf` / `load_env` / `storage_get` / `storage_put`） |
| 夜スロット定数（stdlib 専用・GHA 最小依存ジョブ向け） | `scripts/_night_slots.py` |
| scripts の slug↔store_id・店舗一覧 | `scripts/_stores_common.py` |
| scripts の再試行/バックオフ・運用通知(Slack/Discord) | `scripts/_retry_common.py` / `scripts/_ops_notify.py`（※再試行方針は Flask 側 `oriental/clients/http.py`＝500 を再試行しない と意図的に非対称。両 docstring に相互参照） |
| scripts が oriental の純粋モジュールを最小依存で読む | `scripts/_standalone_import.py` |
| ローカル LLM（Ollama）呼び出し・facts 取得・SYSTEM・MODEL | `scripts/_ollama_common.py`（daily/weekly 共通） |
| GHA 監視ジョブの本体 | `scripts/monitor/*.py`（WF は1行で呼ぶだけ） |
| JST の日付部品・YYYY-MM-DD/HH:MM・夜窓(19時境界)・夜セッション(6時境界) | `frontend/src/lib/date/jst.ts` / `nightWindow.ts`（`storeCardRangeSparkline` 等の旧名は `@deprecated` 別名） |
| サーバー側（SSR/ISR）からバックエンドを叩く | `frontend/src/lib/serverSnapshot.ts`（`fetchBackendSnapshot`、タイムアウト引数化） |
| 混雑ラベルの絶対閾値(120/80。判定UIは非表示中だが LINE 下書きで使用) | `frontend/src/lib/store/crowdThresholds.ts` |
| LINE/公開 facts 用の夜窓集計（TS と mjs の鏡像） | `frontend/src/lib/blog/insightFromRange.ts` ↔ `frontend/scripts/lib/insightCore.mjs`（crossCheck テストが一致を固定） |
| BACKEND_URL の既定値・Next の /api 透過プロキシ | `frontend/src/lib/backendUrl.ts` / `frontend/src/lib/api/` |
| ページ metadata（title/description/canonical/OG/Twitter）・OG画像 | `frontend/src/lib/seo/` / `frontend/src/lib/og/` |
| MDX 前処理（frontmatter 除去・見出し抽出） | `frontend/src/lib/blog/mdx.ts` |
| /api/range 行のパース・合計・最新行 | `frontend/src/lib/range/` |
| StoreSnapshot の組立（range→series→now/peak） | `frontend/src/lib/forecast/assembleSnapshot.ts`（型は `lib/forecast/types.ts`） |
| 相席屋の %換算・時間帯ロールアップ | `frontend/src/app/config/stores.ts`（`seatFullnessPercent` 等）/ `frontend/src/lib/store/nightHourlyRollup.ts` |
| 料金計算（オリエンタル/相席屋） | `frontend/src/lib/pricing/computeCost.ts`（相席屋は `computeCostAisekiya.ts`、共有は `computeCostShared.ts`） |
| 退役スクリプト | リポジトリ直下 `archive/`（README に理由）。`scripts/experiments/` は実験専用（本番は依存しない） |
| GA4/GSC の最新値を読む | `scripts/analytics_report.py`（read-only。手順は `docs/ANALYTICS_AGENT_RUNBOOK.md`） |

このファイルの記述と実際のコードが食い違っていたら、コードを信じて `CLAUDE.md` を更新してください。
