# DECISIONS
Last updated: 2026-05-04 (Round 12: schema v6 連休クラスタ + Daily prompt v2 + Weekly Report v2 redesign)
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
23) **推論時利用可能な特徴量のみ追加**: 新しい特徴量は「推論時に 7 日分の history から算出可能」であることが必須条件。`same_dow_last_week_total`（v3）、`extreme_weather`（v5）はこの基準を満たす。
24) **モデルライブラリ**: **LightGBM が本番ロード優先** (2026-04-12〜)。XGBoost はフォールバック保持（ローカル開発・テスト用）。`oriental/ml/model_xgb.py` のファイル名は import 互換のため変更しない。

## Multi-brand decisions (Round 10)
25) **店舗マスタの単一ソース**: `frontend/src/data/stores.json` に全ブランド（`brand` フィールド付き）を持つ。Python 側 (`multi_collect.py`) は読み込み時に `brand="oriental"` だけ `STORES` 変数に入れて従来の Oriental Lounge 処理パイプラインと互換性を保つ。相席屋は別途 `AISEKIYA_STORES` dict を持つ（座席数情報のため）。
26) **`src_brand` カラム**: Supabase `logs` の `src_brand` でブランドを区別。`'oriental'`（Oriental + ag）/ `'aisekiya'`（相席屋）/ 将来 `'jis'` 等を追加予定。
27) **相席屋の人数推計**: 相席屋は人数ではなくパーセンテージ表示のため、`(座席数+VIP)×2 × %` で逆算した推定人数を保存・表示する。**「※推計値」を免責ページで明示**。実測との乖離が判明したら係数を調整する。
28) **新ブランド追加の手順**:
    1. `multi_collect.py` にスクレイピング関数 + 店舗マスタを追加
    2. `frontend/src/data/stores.json` に `brand="新ブランド"` で店舗エントリ追加
    3. Supabase `stores` テーブルに INSERT
    4. `BrandId` 型と `BRAND_DISPLAY_LABEL` を `frontend/src/app/config/stores.ts` に追加
    5. ML モデルは「データが 1 ヶ月以上溜まってから」追加（リアルタイム表示優先）

## Holiday cluster decisions (Round 11, 2026-05-03)
29) **「連休」の操作的定義**: 連続して休業日扱いとなる日のかたまり。**休業日 = 土日 + 法定祝日 (jpholiday) + 振替休日 + お盆 8/13-15 + 年末年始 12/29-1/3**。実装は `oriental/ml/holiday_calendar.py` に集約し、ML 特徴量と `/api/holiday_status` エンドポイントの双方が同じロジックを参照する。
30) **お盆 / 年末年始の固定期間**: お盆 = 8/13-15、年末年始 = 12/29-1/3 で固定。地域差・企業差はあるが、保守メンテ性のため固定値を採用。実データで明確な乖離が見られた場合のみ `holiday_calendar.py` の定数を更新する。
31) **`schema_version` v6**: v5 の 22 列 + `holiday_block_length` (連続休業ブロック日数 0-9) + `holiday_block_position` (0.0=初日 〜 1.0=最終日、平日は中立値 0.5)。GW・お盆・年末年始など連続休業期間を ML が認識できるようにする。**ただし実効性は学習データに連休サンプルが累積した 2027 年 GW 以降から本格化する**(現状 6 ヶ月分のデータでは外挿が弱い)。
32) **連休バナー (`LongHolidayBanner`) は期待値調整目的**: GW・お盆・年末年始の予測精度低下は ML データ不足由来で短期改善困難なため、UI で「乖離が大きくなる傾向があります」と明示してユーザーの期待値を調整する。技術的精度改善ではなく信頼性管理の施策。

## Daily Report prompt v2 decisions (BLOG_REDESIGN_2026_04 Phase 1, 2026-04-19)
33) **観測者ペルソナ**: Daily Report は「夜遊びに詳しい友人がデータを見ながらつぶやく」距離感の自然文 100-200 字。箇条書き禁止、見出し禁止、挨拶禁止。ペルソナを禁止事項羅列より優先することで AI 臭さを除去する。
34) **2 エディションは独立**: 18:00 (`evening_preview`) と 21:30 (`late_update`) は相互参照禁止。**特に late_update は 18:00 の予測には言及しない**。理由: 予測が外れた場合に 21:30 で「予想を外れて」と書くと予測精度の低さが視覚化される。代わりに 21:30 は純粋な「今、こうなっている」観察に徹する。
35) **予測表現は推量形**: 「21時にピークが来ます」(断定) ❌ → 「21時あたりが山になりそう」(推量) ✅。予測が外れたときの読者の信頼損失を最小化する。
36) **`secondary_wave.note` / `gender_note` に AI 指示語を埋めない**: `insightFromRange.ts` で生成する文脈ノートは、AI に渡したものがそのまま本文に書き写される可能性がある。**ユーザー視認可能な観察文として書き、AI 向け指示 (「控えめに言及してよい」「過度に楽観しない」等) は禁止**。

## Weekly Report v2 decisions (WEEKLY_REPORT_REDESIGN_2026_05, 2026-05-03)
37) **Weekly Report の存在意義は「曜日横断パターン + 来週の戦略」**。Daily が「今夜の点」を見せるなら Weekly は「1 週間の線」を見せる。曜日 × 時間帯ヒートマップが Weekly の核心的差別化要因であり、これが無いなら Weekly Report は存続不要。
38) **「夜セッション」の定義**: 19:00 〜 翌 04:59 を 1 つの「夜」として扱う。0-4 時のデータは前日の夜セッションに集計する (例: 日曜 00:00 のデータは土曜の夜)。これによりヒートマップの「日曜深夜が混雑」のような直感に反する表示が消える。`day_hour_heatmap` と `daily_summary` の両方でこのルールを適用。
39) **ヒートマップの軸は時間 (Y) × 曜日 (X)**: 「22 時が週でどう変動するか」を 1 行スキャンで読めるようにするため。曜日 × 時間 (Y/X 入れ替え) では時間軸の比較が縦スキャンになり認知負荷が上がる。
40) **AI 自然文解説は 2 セクション分割**: `last_week_summary` (過去形・観察、Markdown 箇条書き) + `next_week_forecast` (推量形、Markdown 箇条書き) の独立フィールド。1 つの長文で両方を兼ねさせると焦点がぼやけたため。各セクションはリード文 1 行 + 3-5 項目の箇条書き必須 (です・ます調)。
41) **AI 生成失敗時は既存レコードの文章を保持**: Gemini が 429 や parse 失敗で None を返した場合、Supabase の既存 `last_week_summary` / `next_week_forecast` / `ai_commentary` を読み出して新 payload に merge してから upsert する。前回成功した文章が一過性の失敗で消える事故を防ぐ。
42) **Gemini 呼び出しの 429 戦略**: 5s/15s/45s のバックオフで 3 回リトライ → `gemini-2.5-flash-lite` (別クォータ枠) にフォールバック → 全失敗で None 返却。非 429 エラーはリトライしない (即フェイルする。delay しても無意味)。
43) **Gemini JSON parse の二段構え**: `responseSchema` で構造化出力を強制 + `maxOutputTokens=2000` で切断防止 + 万一の破損時は正規表現 (`r'"key"\s*:\s*"((?:[^"\\]|\\.)*)"'`) で各フィールドを抜き出すフォールバックパーサ。1 件でも取れれば「無コメント」より良いという方針。
