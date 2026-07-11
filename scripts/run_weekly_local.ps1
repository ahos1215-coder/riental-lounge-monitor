# MEGRIBI weekly report - local runner (called by Task Scheduler task MEGRIBI-weekly).
# Loads .env.local, then runs the weekly generator with the Ollama (gemma4:12b) backend
# and syncs to Supabase. Uses $PSScriptRoot so the (Japanese) repo path is never a source
# literal (PowerShell 5.1 mis-decodes UTF-8-without-BOM source, which would corrupt paths).
#
# Git publish step (added to fix sitemap.xml staleness — rank4 bug audit):
# generate_weekly_insights.py only writes frontend/content/insights/weekly/*.json to the
# local working tree; it does not commit/push. Since sitemap.ts reads the deployed
# git-tracked bundle, an uncommitted local generation left /reports/weekly/* lastmod frozen
# indefinitely. After a successful generation, this script now stages ONLY that insights
# path (never `git add -A` — this machine has unrelated dirty files), commits if there is
# something staged, rebases on origin/main, and pushes.
# Failure semantics: report generation already succeeded by the time we reach the git
# steps, so ANY git failure (add/commit/pull-rebase/push) is caught, logged via
# Write-Warning, and swallowed -- it must never fail the scheduled task. No retries; a
# failed push/rebase just leaves the commit local (or the rebase aborted) for a human, or
# for the next weekly run, to reconcile. If generation itself fails (non-zero exit from
# the python step), the git publish step is skipped entirely and that exit code propagates.
param([string]$Stores = "all")

$root = Split-Path -Parent $PSScriptRoot   # parent of scripts/ = repo root
$envFile = Join-Path $root ".env.local"

function Write-WeeklyWarn {
  param([string]$Message)
  Write-Warning ("[run_weekly_local {0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $Message)
}

if (Test-Path $envFile) {
  Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
    if ($_ -notmatch '^\s*#' -and $_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $val = $Matches[2].Trim()
      if ($val.Length -ge 2 -and (($val[0] -eq '"' -and $val[-1] -eq '"') -or ($val[0] -eq "'" -and $val[-1] -eq "'"))) {
        $val = $val.Substring(1, $val.Length - 2)
      }
      [Environment]::SetEnvironmentVariable($Matches[1], $val, "Process")
    }
  }
}

$env:INSIGHTS_GENERATE_AI_COMMENTARY = "1"
$env:INSIGHTS_LLM_BACKEND = "ollama"
$env:INSIGHTS_SYNC_SUPABASE = "1"

$py = "C:\Users\ahos1\AppData\Local\Programs\Python\Python314\python.exe"
$script = Join-Path $root "scripts\generate_weekly_insights.py"
& $py $script --stores $Stores --skip-index
$genExitCode = $LASTEXITCODE

if ($genExitCode -ne 0) {
  Write-WeeklyWarn "generate_weekly_insights.py exited $genExitCode; skipping git publish step."
  exit $genExitCode
}

# --- Git publish step ---------------------------------------------------
# Best-effort only: generation above already succeeded, so nothing in this
# block may cause the scheduled task to report failure.
Push-Location $root
try {
  git add -- frontend/content/insights/weekly
  if ($LASTEXITCODE -ne 0) {
    Write-WeeklyWarn "git add failed (exit $LASTEXITCODE); leaving working tree as-is."
  } else {
    git diff --cached --quiet -- frontend/content/insights/weekly
    if ($LASTEXITCODE -eq 0) {
      Write-Host "[run_weekly_local] no staged changes under frontend/content/insights/weekly; nothing to publish."
    } else {
      git commit -m "chore(weekly): 週次インサイトJSONを更新 (自動)"
      if ($LASTEXITCODE -ne 0) {
        Write-WeeklyWarn "git commit failed (exit $LASTEXITCODE); leaving changes staged locally for manual follow-up."
      } else {
        git pull --rebase --autostash origin main
        if ($LASTEXITCODE -ne 0) {
          Write-WeeklyWarn "git pull --rebase failed (exit $LASTEXITCODE), likely a rebase conflict; aborting rebase and leaving the commit local (unpushed)."
          git rebase --abort *> $null
        } else {
          git push origin main
          if ($LASTEXITCODE -ne 0) {
            Write-WeeklyWarn "git push failed (exit $LASTEXITCODE); commit remains local and will be picked up (rebased + pushed) on a future run."
          }
        }
      }
    }
  }
} catch {
  Write-WeeklyWarn "unexpected error during git publish: $($_.Exception.Message)"
} finally {
  Pop-Location
}

exit 0
