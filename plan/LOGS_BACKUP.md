# LOGS_BACKUP — `logs` テーブルのバックアップと復元

`logs` は全 ML 学習の唯一の正本（再取得不能な約96万行の5分刻み人数履歴）。DB レベルのバックアップが無く、`cleanup_old_logs.py` が毎週自動削除も行うため、事故・誤削除・Supabase 障害で **ML 能力ごと消滅**するリスクがあった。これを `backup-logs.yml`（週次 GHA）で解消する。

## 仕組み

```
backup-logs.yml（毎週 日 21:00 UTC = 月 06:00 JST、cleanup の前）
  └─ scripts/backup_logs.py  … logs 全行を gzip NDJSON にダンプ（読み取り専用）
  └─ gpg AES256 で暗号化（BACKUP_PASSPHRASE）
  └─ GitHub Release `logs-backup-YYYYMMDD` に暗号化ファイルを添付
  └─ 古い世代は最新 8 件まで保持（それ以前は自動削除）
```

> **このリポジトリは public。** だからバックアップは **必ず暗号化**してから Release に上げる。`BACKUP_PASSPHRASE` 未設定時はジョブが **失敗して中断**し、平文を絶対に公開しない（fail-closed）。

## 初回セットアップ（1回だけ・オーナー作業）

1. 強いパスフレーズを生成し、**パスワードマネージャ等に保管**する（例: `openssl rand -base64 32`）。
   - ⚠️ **このパスフレーズを失うとバックアップは復元不能**。バックアップ本体とは別の場所に必ず保管する。
2. GitHub → リポジトリ **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `BACKUP_PASSPHRASE` / Value: 上記パスフレーズ
3. Actions → **Backup logs table** → **Run workflow** で初回を手動実行し、Release `logs-backup-YYYYMMDD`（encrypted）が作成されることを確認。

## 復元手順（DR）

```bash
# 1) 最新のバックアップ Release から暗号化ファイルを取得
gh release download logs-backup-YYYYMMDD -p '*.gpg'

# 2) 復号 + 解凍（パスフレーズを入力）
gpg -d logs-backup-YYYYMMDD.ndjson.gz.gpg | gunzip > logs.ndjson

# 3) Supabase へ再投入（どちらか）
#  a. psql で COPY（最速）: jq で TSV 化して \copy、または
#  b. REST upsert（少量/部分復旧向け）。重複は (store_id, ts) で merge。
#     ※ logs に UNIQUE 制約が無い場合、復元前に重複防止の対応を検討する。
```

NDJSON は「1行 = 1レコードの JSON」。列は `id, store_id, ts, men, women, total, weather_code, weather_label, temp_c, precip_mm, src_brand`。

## 関連

- 収集（書き込み）: `multi_collect.py` / `oriental/routes/tasks.py`
- 自動削除: `scripts/cleanup_old_logs.py` ＋ `.github/workflows/cleanup-old-logs.yml`（バックアップの**後**に走るようスケジュール済み）
- 失敗通知: `notify-on-failure.yml`（`OPS_NOTIFY_WEBHOOK_URL` 設定時）

## 改善余地（任意）

- `logs` に `(store_id, ts)` の UNIQUE 制約＋マイグレーションを追加（復元時の重複防止・収集の冪等化）。
- 容量が増えたら増分バックアップ（前回 `id` 以降のみ）への切替を検討。
