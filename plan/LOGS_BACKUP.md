# LOGS_BACKUP — `logs` テーブルのバックアップと復元

`logs` は全 ML 学習の唯一の正本（再取得不能な約96万行の5分刻み人数履歴）。DB レベルのバックアップが無く、`cleanup_old_logs.py` が毎週自動削除も行うため、事故・誤削除・Supabase 障害で **ML 能力ごと消滅**するリスクがあった。これを `backup-logs.yml`（週次 GHA）で解消する。

## 仕組み

```
backup-logs.yml（毎週 日 03:00 UTC = 日 12:00 JST、cleanup の前）
  └─ scripts/backup_logs.py  … logs 全行を gzip NDJSON にダンプ（読み取り専用）
  └─ gpg AES256 で暗号化（BACKUP_PASSPHRASE）
  └─ GitHub Release `logs-backup-YYYYMMDD` に暗号化ファイルを添付
  └─ 古い世代は最新 8 件まで保持（それ以前は自動削除）
  └─ 12週（84日）に1回、同じファイルを `logs-archive-YYYYMMDD` にも保存（永久保存。消さない）
```

**永久アーカイブ（2026-09-26 追加）**: DB 容量（無料プラン 500MB）に収めるため、`cleanup_old_logs.py` は
行数が 145万行を超えると古い順に消す（普段の夜は約8〜9か月ぶん残る。直近2年の特別な夜＝年末年始・クリスマス・
GW・お盆・大型連休・ハロウィンは、去年と比べられるよう飛ばして残す）。週次バックアップは約2か月で消えるので、
それだけだと古い行は永久に失われる。そこで 12週ごとに全量を `logs-archive-*` として残す。DB に約9か月半ぶん
残っている間に次のアーカイブを撮るので、重なりながら全期間を覆う（取りこぼしなし）。1本 約20MB・年4本。
直近のアーカイブから84日たっていない週は何もしない。撮れなかった週があっても、次に成功した回で撮り直す。
古い期間を復元したいときは、その期間を含む `logs-archive-*` を下の手順で取得する。

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
