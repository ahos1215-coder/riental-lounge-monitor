# Next.js dev の二重起動・lock 残りを解消（Windows 向け）
# 使い方: npm run dev:clean のあと、ターミナルで npm run dev

$ErrorActionPreference = "SilentlyContinue"
$frontendRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $frontendRoot ".next\dev\lock"

foreach ($port in 3000, 3001) {
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    $procId = $c.OwningProcess
    if ($procId) {
      Write-Host "Stopping PID $procId (port $port) and child processes"
      # Stop-Process だけだと npm の子 node が残ることがあるため /T でツリーごと終了
      & taskkill.exe /PID $procId /T /F 2>$null
    }
  }
}

Start-Sleep -Milliseconds 500

if (Test-Path $lockPath) {
  Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
  if (Test-Path $lockPath) {
    Write-Host "WARN: Could not remove lock (file may still be open). Close other terminals and retry."
  } else {
    Write-Host "Removed .next/dev/lock"
  }
} else {
  Write-Host "No lock file (already clean)"
}

Write-Host "Done. Run: npm run dev"
