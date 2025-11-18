# ONBOARDING.md — Oriental Lounge Monitor 引継ぎ用クイックスタート

このプロジェクトは「オリエンタルラウンジ来店人数モニター」の **Flask バックエンド** です。Render(Starter) にデプロイされ、cron-job.org から `/tasks/tick` と `/health` に定期アクセスしています。本書は新しい担当者/次のChatGPTが最短で把握・運用できるようにまとめたクイックスタートです。

---
## 1. リポジトリ
- GitHub: `https://github.com/ahos1215-coder/riental-lounge-monitor`
- ブランチ: `main`
- ドキュメント: `plan/` 配下（RUNBOOK.md / ENV.md / CRON.md / CODEx_PROMPTS.md など）

## 2. 必要環境
- Python 3.13 系（Render も 3.13.4）
- pip
- Windows 11 + PowerShell での動作を想定
- Render アカウント（Starter）
- cron-job.org アカウント

## 3. セットアップ（ローカル）
```powershell
git clone https://github.com/ahos1215-coder/riental-lounge-monitor.git
cd riental-lounge-monitor
pip install -r requirements.txt

# 任意: テストを実行
python -m compileall .
pytest -q

# 起動
python app.py
# http://127.0.0.1:5000 で応答
```

## 4. 環境変数（既定値は ENV.md を参照）
- `TARGET_URL` (例: https://oriental-lounge.com/stores/38)
- `STORE_NAME` (例: 長崎店)
- `WINDOW_START` = 19, `WINDOW_END` = 5
- `HTTP_TIMEOUT_S` = 12, `HTTP_RETRY` = 3
- `MAX_RANGE_LIMIT` = 50000  ← `/api/range?limit=` の上限。範囲外はクランプされます。
- `GS_READ_URL`, `GS_WEBHOOK_URL` （任意：Sheets 連携用）

## 5. 実装上の重要仕様（要点）
- `/api/range` の `limit` は **1..MAX_RANGE_LIMIT** にクランプ。0 や負数、過大値でも **422 ではなく 200** を返し、内部で補正します。
- `/api/meta` `/api/heatmap` `/api/stores/list` `/api/forecast_today` `/api/range_prevweek` `/api/summary` は現状スタブで常に 200/{"ok":true,...}。
- ログは `data/log.jsonl` に JSON で追記（Render では標準出力）。
- テストは `tests/`。`pytest.ini` で `pythonpath=.` 指定済み。

## 6. 本番（Render）
- サービス URL: `https://riental-lounge-monitor.onrender.com`
- デプロイ方式: GitHub の `main` push で Auto-Deploy（Events で確認）
- 環境変数: Render ダッシュボード > Environment で設定
- ログ: Render > Logs
- ロールバック: Events 画面の対象デプロイから `Rollback`

## 7. ヘルス・データ収集
- cron-job.org
  - `/tasks/tick` … **5分ごと**
  - `/health?t={{UNIXTIME}}` … **30分ごと**
  - タイムゾーン: Asia/Tokyo を推奨
- ダッシュボードで `Enable job` を維持

## 8. スモークテスト（本番）
```powershell
iwr "https://riental-lounge-monitor.onrender.com/api/range?limit=0" | Select -Expand Content
iwr "https://riental-lounge-monitor.onrender.com/api/range?limit=120000" | Select -Expand Content
iwr "https://riental-lounge-monitor.onrender.com/api/meta?store=nagasaki" | Select -Expand Content
iwr "https://riental-lounge-monitor.onrender.com/api/summary?store=nagasaki" | Select -Expand Content
```

## 9. よくある質問
- **Q. limit=0 は 422 じゃないの？**  
  A. 運用上「失敗しない API」を優先し、クランプ仕様としています（1 に補正して 200）。
- **Q. データが空（rows: []）なのは？**  
  A. その時間帯に収集データが無いか、`TARGET_URL` 先が閉店時間など。`/tasks/tick` の稼働と `log.jsonl` を確認。

## 10. 次に読むべきファイル
- `plan/RUNBOOK.md` … 日常運用・障害対応手順
- `plan/ENV.md` … Render の環境変数定義
- `plan/CRON.md` … cron-job.org の設定
- `plan/CODEx_PROMPTS.md` … 定期的な堅牢化プロンプト集
- `plan/API_CONTRACT.md` … 現行 API 仕様
- `plan/ARCHITECTURE.md` … 全体構成と将来拡張
