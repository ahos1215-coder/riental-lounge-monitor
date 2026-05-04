# Weekly Insights の調整ガイド
Last updated: 2026-05-04 (v2 redesign のフィールド追加 + AI commentary 環境変数追加)

> **いつ触るか**: パイプライン稼働後、**数日〜1週間分の JSON が溜まってから**閾値や説明文をいじると、実データに基づいて判断しやすい（`plan/VISION_AND_FUTURE.md` フェーズ A）。
>
> v2 redesign の詳細は `plan/WEEKLY_REPORT_REDESIGN_2026_05.md` を参照。

## 生成の入口

- **スクリプト**: `scripts/generate_weekly_insights.py`
  - `--stores <slug>`: 対象店舗（1店舗 or カンマ区切り）
  - `--skip-index`: `index.json` の書き込みをスキップ（Fan-in Matrix の各 matrix ジョブで使用）
- **GitHub Actions**: `.github/workflows/generate-weekly-insights.yml`（Fan-in Matrix 構成）
  - **Fan-out** `generate-store`: 38 店舗を `max-parallel: 10` で並列実行（`--skip-index` あり）
  - **Fan-in** `collect-and-commit`: Artifact を集約して `index.json` を再構築し Git commit 1回
- **出力**:
  - `frontend/content/insights/weekly/<store>/<date>.json`（各店舗 JSON）
  - `frontend/content/insights/weekly/index.json`（Fan-in ジョブが再構築）
  - Supabase `blog_drafts`（`content_type='weekly'`, `is_published=true`）→ `/reports/weekly/[store_slug]` で表示

## JSON に含まれる可視化用フィールド

### 既存 (v1)
- **`series_compact`**: 分析に使った点列を最大約 **240 点**に間引いた時系列（`t`, `occupancy`, `female_ratio`）。**v2 で UI 表示は廃止** (折れ線グラフ削除) されたが、フィールド自体は backward compat のため残置
- **`windows` / `top_windows`**: Good Window 区間（従来どおり）。フロントの「賑わいやすい時間帯」黄色カードで利用
- **`metrics`**: `points_used` / `baseline_p95_total` / `reliability_score`
- **`params`**: `threshold` / `min_duration_minutes` / `ideal` / `gender_weight` / `occupancy_baseline`
- **`period`**: `start` / `end` (集計期間 ISO 8601)

### v2 redesign で追加 (2026-05-03〜)
- **`metric_interpretations`** (Phase A): メトリクスへの解釈ラベル
  - `daily_avg_count` (1日平均件数), `volume_label` (平常 / やや少なめ / 少ない), `baseline_label` (大型店レベル / 中規模店レベル / 小規模店または閑散時間が多め), `period_days` (集計日数)
- **`day_hour_heatmap`** (Phase B): 曜日 × 時間帯ヒートマップ
  - `cells[]` (各セル: `day` 0-6, `hour` 19-23 + 0-4, `avg_occupancy`, `avg_female_ratio`, `sample_count`)
  - `hour_range` ([19,20,21,22,23,0,1,2,3,4]), `day_labels_ja` (["月","火",...]), `max_avg_occupancy` (正規化用最大値)
  - **0-4 時のデータは前日の夜セッションとして集計済み** (例: 日曜 00:00 のデータは土曜行のセル)
- **`daily_summary`** (ポリッシュ): 直近 7 夜分の日別サマリ
  - `[]{date, day_label_ja, avg_occupancy, peak_occupancy, avg_female_ratio, sample_count}`
  - 各「夜」は 19:00-翌04:59 を 1 単位
- **`next_week_recommendations`** (Phase D): 来週の狙い目時間 TOP 3
  - `[]{day, day_label_ja, hour, hour_label, avg_occupancy, avg_female_ratio}`
  - ヒートマップ上位 3 セル (`sample_count >= 2`) から派生
- **`last_week_summary`** (Phase C): AI による先週の傾向 (Markdown 箇条書き、150-280 字)
- **`next_week_forecast`** (Phase C): AI による来週の予想傾向 (Markdown 箇条書き、100-200 字)
- **`ai_commentary`** (Phase C, 後方互換用): `last_week_summary` と `next_week_forecast` を `\n\n` 連結したもの。旧フィールド参照箇所のための保険

## 主な環境変数（GHA の `env` または `export`）

| 変数 | 意味 | スクリプト既定 | GHA 例 |
|------|------|----------------|--------|
| `INSIGHTS_STORES` | 対象店舗スラグ（カンマ/スペース区切り） | （必須） | `shibuya` |
| `INSIGHTS_THRESHOLD` | Good Window のスコア閾値 | `0.40`（スクリプト/GHA 統一済み） | `0.4` |
| `INSIGHTS_MIN_DURATION_MINUTES` | 最小連続分数 | `60` (`DEFAULT_MIN_DURATION_MINUTES`) | `60` |
| `INSIGHTS_IDEAL` | 理想占有率 | `0.7` | 既定 |
| `INSIGHTS_GENDER_WEIGHT` | 男女比の重み | `1.5` | 既定 |
| `MEGRIBI_BASE_URL` / `NEXT_PUBLIC_BASE_URL` | `/api/range` の取得先 | `https://www.meguribi.jp` | 本番 URL |
| `INSIGHTS_HTTP_TIMEOUT_SECONDS` | HTTP タイムアウト | `60` | `90` |
| `INSIGHTS_HTTP_RETRIES` | リトライ回数 | `3` | `4` |
| `INSIGHTS_SYNC_SUPABASE` | `"1"` で Supabase upsert を実行 | `false` | `"1"` |
| `INSIGHTS_GENERATE_AI_COMMENTARY` | **2026-05-03〜**。`"1"` で AI 自然文解説 (last_week_summary + next_week_forecast) を Gemini で生成。OFF なら該当フィールドは空 | `false` | `"1"` |
| `GEMINI_API_KEY` | Gemini API キー (上記フラグ ON 時に必須) | — | Secret |
| `SUPABASE_URL` | Supabase プロジェクト URL | — | Secret |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role Key | — | Secret |

CLI 引数 `--threshold` / `--min-duration-minutes` / `--limit` / `--skip-index` は環境変数より優先されます。

## 調整の観点（実データが溜まってから）

1. **`INSIGHTS_THRESHOLD`**: 高すぎるとウィンドウがほぼ出ない。低すぎるとノイズが増える。`top_windows` と `windows` の件数を見て決める。
2. **`INSIGHTS_MIN_DURATION_MINUTES`**: 短すぎるとちらつき、長すぎると「おすすめ枠」が空になりやすい。
3. **`metrics.reliability_score`**: `points_used` が少ない店舗は UI 側で注意書きを足す余地あり（別タスク）。
4. **Actions の失敗**: Render スリープ・タイムアウトで黙って落ちることがある → `plan/ROADMAP.md` の「GHA 失敗通知」とセットで検討。

## AI 自然文解説の運用 (2026-05-03〜)

### 出力構造
- システムプロンプト要件: です・ます調 + Markdown 箇条書き必須 (リード文 1 行 + 3-5 項目)
- Gemini 設定: `responseSchema` で 2 フィールドを STRING で要求、`maxOutputTokens=2000`、`temperature=0.7`
- フロントは ReactMarkdown + remarkGfm で `<ul><li>` レンダ (SEO 強化)

### 耐障害性の設計
1. **JSON parse 失敗**: 正規表現フォールバックパーサ (`_extract_commentary_via_regex`) で各フィールド単独抽出
2. **429 レート制限**: 5s/15s/45s バックオフで 3 回リトライ
3. **モデル枯渇**: `gemini-2.5-flash` 失敗で `gemini-2.5-flash-lite` (別クォータ枠) にフォールバック
4. **全失敗時**: 既存 Supabase レコードから前回の `last_week_summary` / `next_week_forecast` / `ai_commentary` を読み出して新 payload に merge → 上書き消失防止

### Gemini 無料枠との関係
- 1 週次実行 = 38 店舗 × 1 コール = 38 コール (max-parallel=10 で 4 バッチ)
- Daily Report が同じキーで 76 コール/日使うため、累計次第で 1 日のクォータ (~250-1500) を圧迫することあり
- 失敗時はフォールバック保持機構が動作するため、サイト表示は壊れない

## 関連

- `plan/RUNBOOK.md`（定期ジョブの流れ）
- `plan/STATUS.md`（週次 Insights の位置づけ）
