[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Slug,
  [string]$Title = "",
  [string]$Description = "10秒でわかる結論：到着目安と避けたい時間だけ先に。",
  [string]$CategoryId = "guide",
  [string]$Level = "easy",
  [string]$StoreId = "",
  [string]$FactsId = "",
  [ValidateSet("show","hide")][string]$FactsVisibility = "show",
  [string]$Date = ""  # YYYY-MM-DD（空なら今日）
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$path, [string]$text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  $dir = Split-Path -Parent $path
  if ($dir -and !(Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  [IO.File]::WriteAllText($path, $text, $enc)
}

function Escape-YamlDq([string]$s) {
  if ($null -eq $s) { return "" }
  return ($s -replace '"','\"')
}

$frontendDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($Date)) {
  $Date = (Get-Date).ToString("yyyy-MM-dd")
}

if ([string]::IsNullOrWhiteSpace($Title)) {
  $Title = $Slug
}

if ([string]::IsNullOrWhiteSpace($FactsId)) {
  $FactsId = $Slug
}

$templatePath = Join-Path $frontendDir "content\blog\_templates\_TEMPLATE.mdx"
if (!(Test-Path $templatePath)) { throw "template not found: $templatePath" }

$mdxDir = Join-Path $frontendDir "content\blog"
$factsDir = Join-Path $frontendDir "content\facts\public"
New-Item -ItemType Directory -Force $mdxDir | Out-Null
New-Item -ItemType Directory -Force $factsDir | Out-Null

$mdxPath = Join-Path $mdxDir "$Slug.mdx"
if (Test-Path $mdxPath) { throw "already exists: $mdxPath" }

# --- template body を抽出（frontmatter があれば剥がす）
$raw = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8
$body = $raw -replace '^\s*---[\s\S]*?---\s*\r?\n', ''

# --- frontmatter を標準形で再生成（揺れ吸収のため互換キーも入れる）
$titleEsc = Escape-YamlDq $Title
$descEsc  = Escape-YamlDq $Description

$fm = @()
$fm += '---'
$fm += ('title: "{0}"' -f $titleEsc)
$fm += ('description: "{0}"' -f $descEsc)
$fm += ('date: "{0}"' -f $Date)
$fm += ('categoryId: "{0}"' -f $CategoryId)
$fm += ('category: "{0}"' -f $CategoryId)       # 互換
$fm += ('level: "{0}"' -f $Level)
if ($StoreId.Trim()) {
  $fm += ('storeId: "{0}"' -f $StoreId)
  $fm += ('store: "{0}"' -f $StoreId)           # 互換
}
$fm += ('factsId: "{0}"' -f $FactsId)
$fm += ('facts_id: "{0}"' -f $FactsId)          # 互換
if ($FactsVisibility -eq "hide") {
  $fm += 'facts_visibility: "hide"'
}
$fm += '---'
$fmText = ($fm -join "`r`n") + "`r`n"

# --- template のプレースホルダも一応置換（あれば効く）
$out = $fmText + $body
$out = $out.Replace("__TITLE__", $Title).Replace("__DESCRIPTION__", $Description).Replace("__DATE__", $Date)
$out = $out.Replace("__CATEGORY__", $CategoryId).Replace("__LEVEL__", $Level).Replace("__STORE__", $StoreId).Replace("__FACTS__", $FactsId)
$out = $out.Replace("__PEAK__", "21:30").Replace("__AVOID__", "20:00")

Write-Utf8NoBom $mdxPath $out
Write-Host "created: $mdxPath"

# --- facts json stub を作成（存在すれば触らない）
$factsPath = Join-Path $factsDir "$FactsId.json"
if (!(Test-Path $factsPath)) {
  $toDate = ([datetime]::ParseExact($Date, "yyyy-MM-dd", $null)).AddDays(1).ToString("yyyy-MM-dd")
  $facts = [ordered]@{
    facts_id = $FactsId
    store    = $StoreId
    range    = [ordered]@{
      label = "Tonight"
      from  = "$Date`T19:00:00+09:00"
      to    = "$toDate`T05:00:00+09:00"
    }
    insight  = [ordered]@{
      peak_time   = "21:30"
      avoid_time  = "20:00"
      crowd_label = "混み始め"
    }
    quality_flags = [ordered]@{
      notes = @("preview: stub values")
    }
  }

  ($facts | ConvertTo-Json -Depth 6) | ForEach-Object { $_.Replace("`n", "`r`n") } | Write-Utf8NoBom $factsPath
  Write-Host "created: $factsPath"
} else {
  Write-Host "skip   : $factsPath (exists)"
}

Write-Host ""
Write-Host "Next:"
Write-Host "  npm run dev"
Write-Host "  http://localhost:3000/blog/$Slug"
Write-Host ""
Write-Host "Hide Facts:"
Write-Host "  -FactsVisibility hide  を付ける or mdx の frontmatter に facts_visibility: ""hide"""