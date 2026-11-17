<#
.SYNOPSIS  Stop the recorders started by start_recording.ps1 and summarise what was captured.
.EXAMPLE   .\tools\stop_recording.ps1            # newest data\session_*
#>
param([string]$Session = "")
$root = Split-Path $PSScriptRoot -Parent
if (-not $Session) {
  $Session = (Get-ChildItem (Join-Path $root "data") -Directory -Filter "session_*" | Sort-Object Name | Select-Object -Last 1).FullName
}
$pidFile = Join-Path $Session "recording_pids.json"
if (-not (Test-Path $pidFile)) { Write-Error "no recording_pids.json in $Session"; exit 1 }
$p = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($name in "hotkeys", "logger", "tshark") {
  $id = $p.$name
  $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
  if ($proc) { Stop-Process -Id $id -Force; Write-Host "stopped $name (pid $id)" } else { Write-Host "$name (pid $id) was not running" -ForegroundColor Yellow }
}
Start-Sleep -Milliseconds 500
Rename-Item $pidFile ($pidFile + ".stopped_" + (Get-Date -Format "HHmmss"))
Write-Host "`nFiles in session:"
Get-ChildItem $Session -Recurse -File | Where-Object { $_.Extension -in ".pcapng", ".jsonl" } |
  Select-Object @{n = "file"; e = { $_.FullName.Substring($Session.Length + 1) } }, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 2) } }, LastWriteTime |
  Format-Table -AutoSize
