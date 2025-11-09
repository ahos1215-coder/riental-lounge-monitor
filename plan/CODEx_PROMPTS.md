# CODEx_PROMPTS.md — Oriental Lounge Monitor
最終更新: 2025-11-09  
用途: VS Code の GPT-5 Codex チャット/エージェントに貼り付けて使う「即戦力プロンプト集」。  
対象: Flask(blueprints) / Pydantic v2 / Render(Starter) / Gunicorn / GAS 連携。

---

## 0. ゴールと前提（Codex が必ず守るルール）
- **公開インターフェースを壊さない**: `/healthz`, `/api/current`, `/api/range`, `/tasks/collect`（およびダミー `/api/meta|heatmap|stores/list|forecast_today|range_prevweek|summary` は 200/ok を維持）  
- **検証**: Pydantic v2 を用いた入力・クエリ検証。ユーザー入力エラーは 4xx（基本 422）。  
- **設定**: 機密はすべて環境変数（`AppConfig.from_env()`）から取得。ハードコード禁止。  
- **ログ**: 構造化ログ（`oriental.utils.log`）で重要イベントに `event_key` を付与（例: `api_range.start`, `api_range.success`）。  
- **可観測性**: `/api/range` の `limit` は `MAX_RANGE_LIMIT` に **クランプ**。ログにも最終値を残す。  
- **安全**: 例外はキャッチして 5xx 化・ログ出力、GAS への外部呼び出しはタイムアウト・リトライ・バックオフ付き。  
- **テスト**: `python -m compileall .` が成功すること。`tests/` のスモークが通ること。  
- **デプロイ互換**: `Procfile: web: gunicorn wsgi:app`、Render の Python 3.13 を前提。

プロジェクト主構成（要点）:
```
app.py / wsgi.py
oriental/
  routes/ (health.py, data.py, tasks.py)
  schemas/ (payloads.py)
  clients/ (gas_client.py, http.py)
  utils/ (log.py, storage.py, timeutil.py)
  templates/ (index.html)
data/ (data.json, log.jsonl)
```

---

## 1) マスタープロンプト（堅牢化＆整頓フルパス）
下記を **そのまま** 貼り付けて指示。必要に応じて追加要望を末尾に列挙。

```text
あなたは「Flask + Pydantic v2 + Gunicorn + Render(Starter)」のシニアバックエンドエンジニアです。
目的は「壊さず堅牢化・整理整頓・読みやすさ向上・軽量テスト追加」です。

【与件・制約】
- 既存の公開APIは互換維持: /healthz, /api/current, /api/range, /tasks/collect
- ダミーAPI群（/api/meta, /api/heatmap, /api/stores/list, /api/forecast_today, /api/range_prevweek, /api/summary）は常に200/{"ok":true,...}
- Pydantic v2 に統一。バリデーションとエラー整形（422）を実装・点検。
- AppConfig.from_env() で設定を収束。MAX_RANGE_LIMIT による limit クランプ必須。ログにも最終値を出力。
- 構造化ログ（utils/log.py）で event_key を統一。例外は stacktrace 付き。
- 依存: Flask, requests, gunicorn, beautifulsoup4, lxml, pydantic>=2.8, python-dateutil
- Procfile: web: gunicorn wsgi:app

【出力フォーマット】
1) 変更計画（箇条書き）: 安全性/可読性/運用観点の意図を短く
2) ファイル別パッチ: <<<PATCH filename>>> ～ <<<END>>> で囲み、最小差分
3) 動作確認コマンド: curl スモーク・compileall・簡易pytest（存在する場合）
4) 受け入れ基準の自己チェック: 全て満たすことを宣言

【必須修正ポイント】
- /api/range のクエリ正規化（from/to の妥当性、空時の today 補完、limit clamp）
- tasks/collect のスキーマ検証・GAS 送信のタイムアウト/リトライ
- ログ: start/success/warn/error を event_key で統一
- 404 を出さないダミーAPIの簡潔実装
- 型ヒント・Docstring・例外設計の整理

以上を踏まえ、提案ではなく **直接適用可能なパッチ** を提示してください。
```

---

## 2) モジュール分割・整理だけやりたいとき
```text
既存のコードを壊さず、以下を実施してパッチ形式で提示してください。

- Blueprints を routes/ に整理（health.py, data.py, tasks.py）
- スキーマ: schemas/payloads.py（Pydantic v2）
- 設定: oriental/config.py（AppConfig.from_env）
- ログ: oriental/utils/log.py の adapter を使う
- 既存 import を新配置に合わせて修正（循環回避）
- 変更範囲は最小化。外部I/Fは維持。
```

---

## 3) バリデーション強化だけやりたいとき
```text
Pydantic v2 で /tasks/collect と /api/range の検証を強化し、422 エラー整形も実装。
limit クランプは AppConfig.max_range_limit を用いる。パッチ形式で提示。
```

---

## 4) 構造化ログの統一
```text
構造化ログを event_key ベースに統一。info/warning/error で必ず event_key を入れる。
対象: data.py, tasks.py, health.py, clients/gas_client.py。変更は最小。パッチ形式。
```

---

## 5) スモーク & 受け入れ基準生成
```text
次を出力してください。
- PowerShell 用スモークコマンド（本番URL/ローカル両方）
- 期待ログ例（api_range.start / success）
- 受け入れ基準チェックリスト（箇条書き）
```

---

## 6) エラーパターン洗い出し & 最小修正
```text
try/except 漏れ・境界値・時刻/タイムゾーン・None/空配列・GAS 応答エラーなど、
落ちうるパスを列挙→各1行〜数行の最小修正パッチで提示。
```

---

## 7) 小さな性能改善
```text
/ api/range の I/O 削減・簡易キャッシュ（同一クエリ短時間は再利用）案、
または JSON ロードのホットパス最適化を最小の差分で。可観測性は維持。
```

---

## 8) テスト雛形の生成
```text
pytest 雛形（tests/test_health.py, test_range_params.py, test_collect_validate.py）を
現行の仕様に合わせて最小限で整え、`python -m compileall .` が通ること。パッチ形式。
```

---

## 9) README/RUNBOOK 自動更新
```text
現状の仕様に合わせて README と RUNBOOK の該当セクションを更新。
変更点のみのパッチを提示。環境変数表とスモークは最新化。
```

---

## 10) デプロイ前後チェック（ワンショット）
```text
以下をまとめて出力:
- Procfile / wsgi の整合性チェック
- requirements.txt の最小 Pin 方針
- Render Logs で見るべきイベントキー一覧
- ロールバック手順の確認
```

---

## 付録A: 受け入れ基準（常設版）
- `python -m compileall .` 成功  
- `/healthz` = 200/ok  
- `/api/range?limit=120000` で **200** かつ **limit=MAX_RANGE_LIMIT** にクランプされ、ログに最終値が出る  
- ダミー6 API は 200 / 404 を出さない  
- `tasks/collect` バリデーション・タイムアウト・リトライあり  
- Render のデプロイが成功し、ダッシュボードが描画される

---

## 付録B: よく使うスモーク（ローカル）
```powershell
python -m compileall .
python app.py
curl.exe -s http://127.0.0.1:5000/healthz | python -m json.tool
curl.exe -s "http://127.0.0.1:5000/api/range?from=2024-11-01&to=2024-11-02&limit=120000" | python -m json.tool
```

---

## 付録C: 注意（破壊を避けるためのNG）
- 既存エンドポイントの URL/戻り形式を**変更しない**  
- 環境変数の既定値を不用意に変えない  
- 例外を握り潰して無音にしない（必ずログ）  
- 大規模改名・広域 import 変更は PR を分ける

---

このファイルは **定期運用のテンプレ** です。月1回の堅牢化パスの入口に使ってください。
