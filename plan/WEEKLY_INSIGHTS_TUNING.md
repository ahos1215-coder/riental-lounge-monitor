# Weekly Insights の調整ガイド
Last updated: 2026-03-23

> **いつ触るか**: パイプライン稼働後、**数日〜1週間分の JSON が溜まってから**閾値や説明文をいじると、実データに基づいて判断しやすい（`plan/VISION_AND_FUTURE.md` フェーズ A）。

## 生成の入口

- **スクリプト**: `scripts/generate_weekly_insights.py`
- **GitHub Actions**: `.github/workflows/generate-weekly-insights.yml`（`workflow_dispatch` と週次 `cron`）
- **出力**: `frontend/content/insights/weekly/<store>/<date>.json` と `index.json`

## JSON に含まれる可視化用フィールド

- **`series_compact`**: 分析に使った点列を最大約 **240 点**に間引いた時系列（`t`, `occupancy`, `female_ratio`）。週次生成を **再実行**すると付与される。無い旧 JSON でもページは動作し、チャート部分はプレースホルダ表示。
- **`windows` / `top_windows`**: Good Window 区間（従来どおり）。

## 主な環境変数（GHA の `env` または `export`）

| 変数 | 意味 | スクリプト既定 | GHA 例 |
|------|------|----------------|--------|
| `INSIGHTS_STORES` | 対象店舗スラグ（カンマ/スペース区切り） | （必須） | `shibuya` |
| `INSIGHTS_THRESHOLD` | Good Window のスコア閾値 | `0.80` | `0.4` |
| `INSIGHTS_MIN_DURATION_MINUTES` | 最小連続分数 | `120` | `60` |
| `INSIGHTS_IDEAL` | 理想占有率 | `0.7` | 既定 |
| `INSIGHTS_GENDER_WEIGHT` | 男女比の重み | `1.5` | 既定 |
| `MEGRIBI_BASE_URL` / `NEXT_PUBLIC_BASE_URL` | `/api/range` の取得先 | `https://www.meguribi.jp` | 本番 URL |
| `INSIGHTS_HTTP_TIMEOUT_SECONDS` | HTTP タイムアウト | `60` | `90` |
| `INSIGHTS_HTTP_RETRIES` | リトライ回数 | `3` | `4` |

CLI 引数 `--threshold` / `--min-duration-minutes` / `--limit` は環境変数より優先されます。

## 調整の観点（実データが溜まってから）

1. **`INSIGHTS_THRESHOLD`**: 高すぎるとウィンドウがほぼ出ない。低すぎるとノイズが増える。`top_windows` と `windows` の件数を見て決める。
2. **`INSIGHTS_MIN_DURATION_MINUTES`**: 短すぎるとちらつき、長すぎると「おすすめ枠」が空になりやすい。
3. **`metrics.reliability_score`**: `points_used` が少ない店舗は UI 側で注意書きを足す余地あり（別タスク）。
4. **Actions の失敗**: Render スリープ・タイムアウトで黙って落ちることがある → `plan/ROADMAP.md` の「GHA 失敗通知」とセットで検討。

## 関連

- `plan/RUNBOOK.md`（定期ジョブの流れ）
- `plan/STATUS.md`（週次 Insights の位置づけ）
