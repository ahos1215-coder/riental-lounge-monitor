# RUNBOOK — Oriental Lounge Monitor

最終更新: 2025-11-09  
担当: ahos1215-coder  
対象環境: Render (Starter) / Python 3.13 / Flask + Gunicorn / Google Apps Script 連携

---

## 1. 概要

- 目的: オリエンタルラウンジ長崎の入店状況を収集・保存・可視化  
- バックエンド: Flask アプリ（`wsgi:app` を Gunicorn で起動）  
- データ保存: GAS 経由で Google スプレッドシート、ローカル運用ログは `data/log.jsonl`  
- 収集トリガ: cron-job.org から 5 分間隔（19:00–翌05:00 JST）で `/tasks/collect`  
- 可視化: テンプレート + Chart.js（ダッシュボード画面）  
- 本番URL: `https://riental-lounge-monitor.onrender.com`

---

## 2. ディレクトリ構成（要点）

```
oriental/
  clients/      GAS 連携・HTTPクライアント
  routes/       Flask Blueprints（/healthz, /api/*, /tasks/*）
  schemas/      Pydantic v2 スキーマ
  templates/    ダッシュボード（index.html）
  utils/        log, storage, timeutil
wsgi.py         Gunicorn エントリ
app.py          ローカル実行用（開発）
data/           data.json, log.jsonl（運用ログ）
```

---

## 3. 環境変数（Render: Environment → Edit）

| KEY | VALUE（例） | 用途 |
|---|---|---|
| LOG_LEVEL | INFO | 構造化ログレベル |
| TIMEZONE | Asia/Tokyo | 基準タイムゾーン |
| WINDOW_START | 19 | グラフ窓（開始時刻、時） |
| WINDOW_END | 5 | グラフ窓（終了時刻、時・翌日） |
| HTTP_TIMEOUT_S | 12 | 外部HTTPタイムアウト |
| HTTP_RETRY | 3 | 外部HTTPリトライ回数 |
| MAX_RANGE_LIMIT | 50000 | `/api/range` の最大件数（アプリ内でクランプ） |
| GS_WEBHOOK_URL | （GASのPOST URL） | `tasks/collect` 書き込み |
| GS_READ_URL | （GASのGET URL） | `/api/range` 読み取り |

> 機密は必ず環境変数で管理。リポジトリに置かない。

---

## 4. デプロイ運用

### 4.1 自動デプロイ
- Render → Settings → **Auto Deploy: Yes**（main へ push で自動反映）

### 4.2 手動デプロイ
- 画面右上 **Manual Deploy → Deploy latest commit**

### 4.3 ロールバック
- Render → Events → 対象デプロイ → **Rollback**

---

## 5. ローカル開発

```powershell
# 事前: Python 3.13 / VSCode
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 構文チェック
python -m compileall .

# 実行
python app.py
# http://127.0.0.1:5000
```

---

## 6. スモークテスト（本番URLで）

```powershell
# 1) ヘルス
curl.exe -s https://riental-lounge-monitor.onrender.com/healthz | python -m json.tool

# 2) 範囲取得（limit=120000 と指定しても内部で MAX_RANGE_LIMIT (=50000) にクランプ）
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/range?from=2024-11-01&to=2024-11-02&limit=120000" | python -m json.tool
# 期待: HTTP 200 / JSON、Render Logs に
#  api_range.success ... limit=50000

# 3) ダミーAPI（常に200/ok）
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/meta?store=nagasaki" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/heatmap?weeks=8&store=nagasaki" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/stores/list" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/forecast_today?weeks=6&store=nagasaki" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/range_prevweek?from=2024-11-01&to=2024-11-02&limit=50000&store=nagasaki" | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/summary?store=nagasaki" | python -m json.tool
```

---

## 7. 定常運用（ジョブ）

### 7.1 収集（cron-job.org）
- 名称: `collect_5min`  
- Method: `POST`  
- URL: `https://riental-lounge-monitor.onrender.com/tasks/collect`  
- Headers: `Content-Type: application/json`  
- Body（例: テスト時）
  ```json
  {"store":"長崎店","men":12,"women":8,"ts":"{{ISOUTC}}"}
  ```
- Interval: 5分  
- Active window: 19:00–翌05:00 JST

### 7.2 ヘルス
- 名称: `health_15min`  
- Method: `GET`  
- URL: `https://riental-lounge-monitor.onrender.com/healthz`  
- Interval: 15分

---

## 8. 監視

- Render → **Logs**  
  - 期待ログ: `api_range.start` → `api_range.success ... limit=50000`  
- Render → **Metrics**（レスポンス/エラー傾向）  
- ダッシュボードUI（トップ画面）が描画できること

---

## 9. 変更管理

- ブランチ: `feat/*`, `fix/*` → PR → main  
- 事前チェック: `python -m compileall .`  
- タグ付け（任意）: `git tag vX.Y.Z && git push --tags`  
- README / RUNBOOK / CODEx_PROMPTS は更新差分に含める

---

## 10. トラブルシュート

| 症状 | 見る場所 | 即応 |
|---|---|---|
| `/api/range` が遅い/タイムアウト | Render Logs / Metrics | `MAX_RANGE_LIMIT` を `10000` に一時変更して保存（再起動）、再実行 |
| `rows: []` が続く | GAS スプレッドシート / `GS_READ_URL` | シートに行が増えているか確認。日付フォーマット不一致に注意 |
| 502/5xx | Render Logs | 直近デプロイを Rollback。エラースタックを確認 |
| collect が 4xx | Logs（`tasks/collect`） | `GS_WEBHOOK_URL` を再設定。Body のキー名/型を確認 |
| デプロイ後に不安定 | Events → Rollback | 直前の安定コミットに戻す。Auto Deploy を一時 OFF |

---

## 11. バックアップ / リストア

- ログ: `data/log.jsonl` を週次で取得し保存（秘匿情報なし）  
- スプレッドシート: GAS 側で別シートへ定期コピー（フォーマット維持）

---

## 12. 既存エンドポイント仕様（抜粋）

- `GET /healthz` … 200 / 状態サマリ  
- `GET /api/current` … ダッシュボードの現況  
- `GET /api/range?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=N`  
  - `limit` は `MAX_RANGE_LIMIT` を上限に**クランプ**  
  - 正常時 200 / `{ ok, rows: [...] }`  
- `POST /tasks/collect` … GAS へ append  
- ダミーAPI（常に 200 / ok）  
  - `/api/meta`, `/api/heatmap`, `/api/stores/list`, `/api/forecast_today`, `/api/range_prevweek`, `/api/summary`

---

## 13. 品質ゲート（受け入れ基準）

- `python -m compileall .` がエラー無し  
- 本番 `/healthz` が 200  
- `/api/range` へ `limit=120000` 指定時、ログに `limit=50000` と記録（クランプ）  
- ダミー6 API は 200 かつ 404 を出さない  
- ダッシュボードが表示・グラフが描画

---

## 14. 定期メンテ提案

- 月1回: 依存パッケージ更新 → スモーク → デプロイ  
- 月1回: `CODEx_PROMPTS.md` で「堅牢化プロンプト」を回し、差分適用  
- 四半期: GAS 側の応答時間・スプレッドシート肥大を点検（アーカイブ方針）

---

## 15. 付録：よく使うコマンド

```powershell
# ローカル
python -m compileall .
python app.py

# 本番スモーク
curl.exe -s https://riental-lounge-monitor.onrender.com/healthz | python -m json.tool
curl.exe -s "https://riental-lounge-monitor.onrender.com/api/range?from=2024-11-01&to=2024-11-02&limit=120000" | python -m json.tool

# Git
git add .
git commit -m "update: <message>"
git push
```

---

## 16. プロンプト運用（合わせ技）

- 定例の堅牢化: `CODEx_PROMPTS.md` の「1) 堅牢化プロンプト」→「3) 受け入れ基準」で回す  
- 変更が大きい/迷う場合は、都度この Runbook と併用して AI に相談し、差分を最小に
