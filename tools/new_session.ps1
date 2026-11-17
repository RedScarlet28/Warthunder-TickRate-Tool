<#
.SYNOPSIS  Create a new session folder with the standard layout and a filled-in log template.
.EXAMPLE   .\tools\new_session.ps1            -> data\session_20261114_01
#>
param([string]$Root = (Join-Path $PSScriptRoot "..\data"))
$day = Get-Date -Format "yyyyMMdd"
$n = 1
while (Test-Path (Join-Path $Root ("session_{0}_{1:D2}" -f $day, $n))) { $n++ }
$s = Join-Path $Root ("session_{0}_{1:D2}" -f $day, $n)
foreach ($pc in "pcA","pcB") { foreach ($d in "pcap","telemetry","obs","replays") {
  New-Item -ItemType Directory -Force -Path (Join-Path $s "$pc\$d") | Out-Null } }
foreach ($d in "camera","server_replay") { New-Item -ItemType Directory -Force -Path (Join-Path $s $d) | Out-Null }
$tpl = Join-Path $PSScriptRoot "..\templates\session_log.md"
(Get-Content $tpl -Raw).Replace("{{SESSION}}", (Split-Path $s -Leaf)).Replace("{{DATE}}", (Get-Date -Format "yyyy-MM-dd HH:mm")) |
  Out-File -Encoding utf8 (Join-Path $s "session_log.md")
Write-Host "Created $s"
