# ローカルLLM レポート生成 — セットアップ / 復旧手順書

> 全体像は `../CLAUDE.md`（システム3分マップ）と `../plan/BLOG_CRON_GHA.md`（GHA緊急時手順）も参照。

このノートPC（Windows・24時間常時起動）は、日次・週次レポートの文章を**ローカルの
gemma4:12b（Ollama）で無料生成**して Supabase `blog_drafts` に upsert する。
Gemini API へのコスト移行の代替として 2026-07 に構築。GPU (RTX 4060 8GB) は音楽
プロジェクトと共有するため `gpu_lock` で排他する。

このドキュメントは「マシンが飛んだ時にゼロから再構築する」ための最小手順。

---

## 全体像

| 何を | いつ | どう |
|---|---|---|
| 日次レポート（夕方版）| 毎日 18:00 JST | Task Scheduler `MEGRIBI-daily-evening` → `local_report_job.py --edition evening_preview --mode publish` |
| 日次レポート（深夜版）| 毎日 21:30 JST | Task Scheduler `MEGRIBI-daily-late` → `local_report_job.py --edition late_update --mode publish` |
| 週次レポート | 毎週水 06:30 JST | Task Scheduler `MEGRIBI-weekly` → `run_weekly_local.ps1 -Stores all`（内部で `generate_weekly_insights.py`）|

いずれも成否は Supabase `blog_drafts` の `is_published` / `error_message` に記録される
（失敗時は本文空・`is_published=false`・`error_message` あり、という2状態を厳守）。
公開監視は GitHub Actions `check-daily-published.yml` が別途行う（PCが落ちていても検知可）。

---

## 依存関係

- **Python**: `C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe`
- **Ollama**: `http://localhost:11434`、モデル `gemma4:12b`（`ollama pull gemma4:12b`）
- **gpu_lock**: 正本 `C:\Users\Public\共有データ系\gpu_lock.py`（音楽プロジェクトと共有・単一ソース）。
  リポジトリ内 `scripts/gpu_lock.py` は復旧用ミラー。
- **.env.local**（リポジトリ直下、git管理外）に必要なキー（値は載せない）:
  `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `GEMINI_API_KEY`（週次の緊急フォールバック用）
- **本番スクリプト**（すべて `scripts/`）:
  - `local_report_job.py` — 日次生成本体
  - `experiments/local_llm_spike.py` — `fetch_store_facts` / `run_ollama` / `SYSTEM` を提供（`local_report_job.py` が import）
  - `run_weekly_local.ps1` — 週次のラッパ（.env.local読込→`generate_weekly_insights.py`）
  - `generate_weekly_insights.py` — 週次生成本体（`INSIGHTS_LLM_BACKEND=ollama`）
  - `tune_local_llm.py` — 速度チューニングのハーネス（下記）

---

## 速度チューニング（自己改善ループ）

`gemma4:12b`(8.9GB) は 8GB VRAM に収まらず既定では約30%がCPUに退避し ~14 tok/s に律速される。
`tune_local_llm.py` が設定を実測し、品質ゲート合格のうち最速を `local_llm_spike_out/tuning_results.json`
に書き出す。`local_report_job.py` は起動時にこの推奨 options を自動で読む（無ければ従来既定）。

- 2026-07-03 実測の推奨: `num_ctx=2048` + `num_gpu=999`（全層GPU・7.94GB）で **13.7→24.8 tok/s（×1.8）**。
  daily のプロンプトは ~1000 tokens なので 2048 で切り捨てなし（品質同じ）。
- 週次は指示文が長く（最大 ~4000 tokens）2048 では頭が切れるため、この高速化は日次のみ適用。
- 再計測: `python scripts/tune_local_llm.py`（GPUを使うので他ジョブと競合しない時間に）。
- 既知の逆効果（再試行しない）: `OLLAMA_FLASH_ATTENTION=1` + KV q8 は本機で 14→3.4 tok/s に悪化。
- 掃除: `ollama` を強制killすると `llama-server` 子プロセスがVRAMを掴んだまま残る →
  `Get-Process llama-server | Stop-Process` で解放。

---

## ゼロから再構築する手順

1. リポジトリを clone、`.env.local` を作成（上記キーを設定）。
2. Python 3.14 と Ollama をインストール、`ollama pull gemma4:12b`。
3. `gpu_lock.py` を `C:\Users\Public\共有データ系\`（または `SHARED_GPU_LOCK` 環境変数で任意パス）に配置。
   リポジトリの `scripts/gpu_lock.py` をコピーすればよい。
4. 動作確認: `python scripts/local_report_job.py --stores shibuya --edition evening_preview --mode dry-run`。
5. Task Scheduler に3タスクを登録（PowerShell、管理者不要・対話ログオンで可）:

```powershell
# 実行条件の共通設定（撃ち逃し再実行・スリープ復帰・バッテリー可）
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
     -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$py = "C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Users\Public\共有データ系\ORIENTAL\ORIENTAL\riental-lounge-monitor-main"

# 日次 夕方 18:00
schtasks /Create /TN "MEGRIBI-daily-evening" /SC DAILY /ST 18:00 /F `
  /TR "$py $root\scripts\local_report_job.py --kind daily --stores all --edition evening_preview --mode publish"
# 日次 深夜 21:30
schtasks /Create /TN "MEGRIBI-daily-late" /SC DAILY /ST 21:30 /F `
  /TR "$py $root\scripts\local_report_job.py --kind daily --stores all --edition late_update --mode publish"
# 週次 水 06:30（ラッパ経由）
schtasks /Create /TN "MEGRIBI-weekly" /SC WEEKLY /D WED /ST 06:30 /F `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run_weekly_local.ps1`" -Stores all"
# 3タスクとも実行条件を適用
foreach ($t in "MEGRIBI-daily-evening","MEGRIBI-daily-late","MEGRIBI-weekly") { Set-ScheduledTask -TaskName $t -Settings $s }
```

6. GitHub Actions 側: 週次/日次の Gemini cron は無効化済み（`generate-weekly-insights.yml` / `trigger-blog-cron.yml`
   の schedule はコメントアウト、`workflow_dispatch` のみ緊急用に残す）。二重生成（同一 facts_id への
   double-write）を避けるため、ローカルと GHA を同時に定期実行しないこと。
