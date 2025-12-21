param(
  [Parameter(Mandatory = $true)]
  [string]$Slug,

  [Parameter(Mandatory = $true)]
  [string]$Title,

  [string]$Description = "10秒でわかる結論：到着目安と避けたい時間だけ先に。",

  [string]$Date = (Get-Date -Format "yyyy-MM-dd"),

  [Alias("Category")]
  [ValidateSet("guide","beginner","prediction","column","interview")]
  [string]$CategoryId = "guide",

  [Alias("Store")]
  [string]$StoreId = "",

  [ValidateSet("show","hide")]
  [string]$FactsVisibility = "show"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$path, [string]$text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  $dir = Split-Path -Parent $path
  if ($dir -and !(Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  [IO.File]::WriteAllText($path, $text, $enc)
}

function Escape-YamlSingle([string]$s) {
  if ($null -eq $s) { return "" }
  return ($s -replace "'", "''")
}

function Parse-Ymd([string]$ymd) {
  $ci = [Globalization.CultureInfo]::InvariantCulture
  return [datetime]::ParseExact($ymd, "yyyy-MM-dd", $ci)
}

# frontend root は scripts/ の1つ上
$frontendRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$mdxPath   = Join-Path $frontendRoot ("content\blog\{0}.mdx" -f $Slug)
$factsPath = Join-Path $frontendRoot ("content\facts\public\{0}.json" -f $Slug)

# Date から “Tonight (19:00 -> next day 05:00)” を作る
$base = Parse-Ymd $Date
$from = $base.Date.AddHours(19)
$to   = $from.AddHours(10)

$fromStr = $from.ToString("yyyy-MM-dd'T'HH:mm:sszzz")
$toStr   = $to.ToString("yyyy-MM-dd'T'HH:mm:sszzz")

$titleY = Escape-YamlSingle $Title
$descY  = Escape-YamlSingle $Description
$storeY = Escape-YamlSingle $StoreId

$mdx = @"
---
title: '$titleY'
description: '$descY'
date: '$Date'
categoryId: '$CategoryId'
level: 'easy'
store: '$storeY'
facts_id: '$Slug'
factsId: '$Slug'
facts_visibility: '$FactsVisibility'
---

## 10秒まとめ
- 到着目安：21:30台
- 避けたい時間：20:00台

## 今日の一言
短い一文で人間味。

## 理由はこれ（根拠は1つ）
本文は「理由1つ」だけ。数字を散らさず、必要なら下に隔離。

## 初心者メモ
失敗しない動き方。

## くわしく（任意）
グラフや注意点はここに隔離。
"@

# MDX は UTF-8 (no BOM)
Write-Utf8NoBom $mdxPath ($mdx.TrimEnd() + "`r`n")
Write-Host "created: $mdxPath"

# facts JSON は UTF-8 (no BOM)
$facts = [ordered]@{
  facts_id = $Slug
  store    = $StoreId
  range    = [ordered]@{
    label = "Tonight"
    from  = $fromStr
    to    = $toStr
  }
  insight  = [ordered]@{
    peak_time   = ""
    avoid_time  = ""
    crowd_label = ""
  }
  quality_flags = [ordered]@{
    notes = @("preview: stub values")
  }
}

$json = ($facts | ConvertTo-Json -Depth 6)
Write-Utf8NoBom $factsPath ($json.TrimEnd() + "`r`n")
Write-Host "created: $factsPath"

Write-Host ""
Write-Host "Next:"
Write-Host "  1) MDX frontmatter を調整（facts_visibility を hide/show で切替可）"
Write-Host "  2) npm run dev で /blog/<slug> を確認"
