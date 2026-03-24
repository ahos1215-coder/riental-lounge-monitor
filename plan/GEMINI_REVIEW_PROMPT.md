# Gemini 向け：ML 2.0 最終接続レビュー（店舗別モデル）

## いまの論点（2026-03-24 時点）

- 推論APIは稼働し、`/api/forecast_today` は 200 を返す
- 最新は **ML 2.0（店舗別モデル）** 前提で、ブログ生成時は予測値を「混雑回避の提案」に変換する編集品質が重要
- `ModelRegistry` は店舗別優先ロジック実装済み（`store_models` があれば店舗別を読む）
- ただし現行Storage上の `metadata.json` が `has_store_models=false` / `store_models` 空で、実際には `model_men.json` / `model_women.json` のグローバルフォールバックが使われている
- 目的は「店舗別モデルが本当に読まれている状態」を最終証明すること

## アップロード推奨（最大10件）

Geminiに「ドキュメント＋実装の両方」を渡して、机上レビューでなく実装整合まで見てもらう構成です。

| # | ファイル | 目的 |
|---|----------|------|
| 1 | `plan/STATUS.md` | 現在の進捗・既知課題の正本 |
| 2 | `plan/ARCHITECTURE.md` | 3層分離（Web推論 / 収集 / GHA学習）の文脈 |
| 3 | `plan/API_CONTRACT.md` | API契約を壊していないか確認 |
| 4 | `plan/ENV.md` | ML環境変数・重み設定の前提 |
| 5 | `plan/RUNBOOK.md` | 運用手順と検証手順 |
| 6 | `scripts/train_ml_model.py` | `metadata.json` / `store_models` 生成元 |
| 7 | `oriental/ml/model_registry.py` | 店舗別モデル解決・フォールバック実装 |
| 8 | `oriental/ml/forecast_service.py` | 推論・reasoning返却・空配列化ポイント |
| 9 | `oriental/ml/preprocess.py` | 学習/推論の特徴量一致確認 |
| 10 | `tests/verify_store_model_connection.py` | 最終接続テスト（店舗間比較） |

### 差し替え候補（任意）

- `oriental/routes/forecast.py`（HTTP層の正規化/503ハンドリング確認）
- `.github/workflows/train-ml-model.yml`（GHA実行条件とenv受け渡し確認）
- `tests/debug_nagasaki_api.py`（空配列原因の再調査用）

---

## Gemini へのコピペ用プロンプト（日本語）

以下をそのまま Gemini に貼り付け、上表の10ファイルを添付してください。

```
あなたは Next.js + Python/ML 運用に強いシニアアーキテクトです。
以下の添付ファイルを前提に、「店舗別モデル最終接続フェーズ」をレビューしてください。

## 背景
- 目的: `ol_nagasaki` / `ol_shibuya` など店舗別モデルを本番推論で使うこと
- 現状: APIは200で返るが、Storage上のmetadata次第でグローバルモデルへフォールバックしている
- 実装: ModelRegistry側には店舗別優先 + フォールバック維持 + ログ強化を実装済み

## 依頼1（最優先）
`model_registry.py` と `train_ml_model.py` の整合を確認し、
「metadata.json に store_models がある場合は必ず店舗別モデルを読む」ことを保証できているか判定してください。

## 依頼2
以下の故障モードを列挙し、優先度順に対策案を出してください。
- metadataの has_store_models / store_models の不整合
- store_id名寄せ不一致（例: `ol_shibuya_honten` と `ol_shibuya`）
- datedモデル名の選択ミス（YYYYMMDDパース）
- feature_columns不一致による503
- APIは200だが実質グローバルモデル利用のまま気づけない運用事故

## 依頼3
`tests/verify_store_model_connection.py` をベースに、
「店舗別モデル接続成功を判定する最小テスト仕様（合格条件/失格条件）」を提案してください。
特に以下を含めてください。
- 成功ログ文言（store-specific load）
- metadata検証条件
- 店舗間予測差の比較条件
- reasoning の最低検証条件

## 依頼4（ブログ生成品質）
- `insight.avoid_time` は「避ける時間」ではなく、**入店しやすく比較的落ち着いた時間帯の目安**として扱う文体ガイドを提案してください。
- ML 2.0 の推論根拠（reasoning / signals）を、読者価値が高い一文へ変換するテンプレートを3つ提案してください（煽り・断定は禁止）。

## 出力形式
- 見出しは日本語で。
- 重要度は 🔴高 / 🟡中 / 🟢低 を付与
- 「今すぐ直すべき項目（3つ）」を最後に箇条書きで提示
- 根拠のない断定は禁止。推測は「推測:」と明記

最終的に、私が今夜やるべき作業を「手順書（5ステップ以内）」で締めてください。
```

---

Last updated: 2026-03-24
