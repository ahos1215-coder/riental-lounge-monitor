# MEGRIBI weekly report - local runner (called by Task Scheduler task MEGRIBI-weekly).
# Loads .env.local, then runs the weekly generator with the Ollama (gemma4:12b) backend
# and syncs to Supabase. Uses $PSScriptRoot so the (Japanese) repo path is never a source
# literal (PowerShell 5.1 mis-decodes UTF-8-without-BOM source, which would corrupt paths).
param([string]$Stores = "all")

$root = Split-Path -Parent $PSScriptRoot   # parent of scripts/ = repo root
$envFile = Join-Path $root ".env.local"

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
