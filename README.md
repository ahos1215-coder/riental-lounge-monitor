# Oriental Lounge Monitor

堅牢化した Flask + Google Sheets 連携アプリです。構成をモジュール化し、Pydantic v2 によるバリデーションや構造化ログ、HTTP リトライ付きクライアントを備えています。

## ディレクトリ構成

```
oriental/
├─ __init__.py          # Flask アプリ factory
├─ config.py            # 環境変数ベースの設定
├─ routes/              # healthz / api / tasks ルート
├─ clients/             # HTTP 共通クライアント & GAS クライアント
├─ schemas/             # Pydantic モデル
├─ utils/               # logging / time / storage など
└─ templates/           # index.html
```

## 必須環境変数

| 変数 | 役割 | デフォルト |
| --- | --- | --- |
| `TARGET_URL` | スクレイピング対象 URL | https://oriental-lounge.com/stores/38 |
| `STORE_NAME` | 店舗名 | 長崎店 |
| `GS_WEBHOOK_URL` | GAS append 用 URL | 空 (無効) |
| `GS_READ_URL` | GAS range 取得 URL | 空 (無効) |
| `LOG_LEVEL` | 構造化ログのレベル | INFO |
| `HTTP_TIMEOUT_S` | 外部 HTTP タイムアウト秒 | 12 |
| `HTTP_RETRY` | リトライ回数 | 3 |
| `TIMEZONE` | 標準タイムゾーン | Asia/Tokyo |

Render では環境変数をダッシュボードから設定してください。

## ローカル開発

```bash
pip install -r requirements.txt
python app.py  # or use VS Code F5 (launch.json)
```

### VS Code
- F5: `.vscode/launch.json` で `app.py` を直接起動
- `Terminal > Run Task` から Ruff / Black / MyPy / pre-commit を実行

## デプロイ

Procfile で `gunicorn wsgi:app` を起動します。Render でそのまま使用できます。

## テスト / 品質ツール

- `python -m compileall .` : 構文チェック
- `ruff check .`, `black .`, `mypy .` : `.vscode/tasks.json` および `.pre-commit-config.yaml`

## エンドポイント

- `GET /healthz` : ok と設定サマリを返却
- `GET /` : templates/index.html
- `GET /api/current`, `GET /api/range`
- `GET|POST /tasks/collect` (Pydantic 検証付き)
- `GET /tasks/tick`, `GET /tasks/seed`