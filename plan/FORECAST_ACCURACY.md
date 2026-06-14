# FORECAST_ACCURACY — 予測の「答え合わせ」ループ

## 目的

学習時の holdout 精度（`metadata.json` → `/api/forecast_accuracy` → 精度カード）とは別に、
**実際にユーザーへ出した本番予測**が当夜の**実測**とどれだけズレたかを毎日測り、推移を記録する。
これは「学習では良く見えるのに本番では悪い」型のズレ（train/serve skew。天気が推論時に死んでいた等）
を検知する唯一の手段であり、改善（天気修正・目的関数変更・共通モデル等）の効果を**実数**で確認できる。

## 仕組み（2フェーズ・GHA `forecast-accuracy-track.yml`）

```
snapshot (18:10 JST, 夜が始まる前):
  scripts/snapshot_forecasts.py
  └─ 全店の /api/forecast_today_multi（=本番が出す予測）を取得
  └─ その夜の 19:00–05:00 予測カーブを Supabase Storage に保存
     <bucket>/accuracy/snapshots/<YYYYMMDD>.json   （補正なしの純粋な事前予測）

score (06:10 JST, 夜が終わった後):
  scripts/score_forecasts.py
  └─ 前夜の snapshot を読む
  └─ logs から前夜 19:00–05:00 の実測を取得
  └─ 15分スロットで突き合わせ、店舗別の「本番予測 MAE（live_mae）」を算出
  └─ 保存:
     <bucket>/accuracy/scores/<YYYYMMDD>.json   （その夜の店舗別 live MAE）
     <bucket>/accuracy/scores/summary.json      （直近60夜の推移・新しい順）
```

- **新規インフラ不要**：DBテーブルもバケットも作らない。既存のモデル用バケット
  （`FORECAST_MODEL_BUCKET`、既定 `ml-models`）の `accuracy/` プレフィックスに保存。
- **シークレット**：既存の `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` を使用。`BACKEND_URL` は
  リポジトリ変数（未設定なら本番 onrender URL にフォールバック）。

## 使い方 / 確認

- 手動実行：Actions → **Forecast accuracy tracking** → Run workflow → `mode` に `snapshot` か `score`。
- 結果はジョブログに店舗別 live MAE が表示される。推移は Storage の `accuracy/scores/summary.json`。
- snapshot は **18:10**（純粋な事前予測）を採点対象にする。21:30 便の実測ベース表示や (b) の
  tonight-anchoring とは独立。

## 学習 holdout 精度との違い（重要）

| | 学習 holdout MAE（精度カード） | live MAE（このループ） |
|---|---|---|
| 対象 | 過去データの 2 割（学習時） | 昨夜ユーザーに出した実予測 |
| 検知できるもの | モデルの素の当てはまり | train/serve skew・本番限定の劣化 |
| 例 | 天気が実測で効くか | 天気が**推論時に死んでいた**ことを検知 |

両者を**併読**することで、「学習は良いのに本番が悪い」を切り分けられる。

## 改善余地（任意）

- フロント表示（「昨夜: 予測◯人 / 実測△人」）を `/store/[id]` に追加。
- live MAE が閾値を超えた夜に `OPS_NOTIFY_WEBHOOK_URL` で通知。
- snapshot を edition ごと（18時便/21時半便）に保存し、(b) anchoring の効果も live で比較。
