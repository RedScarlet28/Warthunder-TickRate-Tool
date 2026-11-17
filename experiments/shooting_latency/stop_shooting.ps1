<#
.SYNOPSIS  Stop the shooting-experiment recorders on this PC and list the files.
.EXAMPLE   .\stop_shooting.ps1                 # today's session
           .\stop_shooting.ps1 -Session 20261114
#>
param([string]$Session = (Get-Date -Format "yyyyMMdd"))
$out = Join-Path $PSScriptRoot ("data\{0}\{1}" -f $Session, $env:COMPUTERNAME)
$pidFile = Join-Path $out "shooting_pids.json"
if (-not (Test-Path $pidFile)) { Write-Error "no shooting_pids.json in $out"; exit 1 }
$p = Get-Content $pidFile -Raw | ConvertFrom-Json
# graceful stop: recorders watch for a STOP file and close their files cleanly
New-Item -ItemType File -Force -Path (Join-Path $out "STOP") | Out-Null
Write-Host "Asked recorders to stop, waiting for them to close their files..."
$deadline = (Get-Date).AddSeconds(6)
while ((Get-Date) -lt $deadline) {
  $running = @("audio", "inputs", "clock") | Where-Object { $p.$_ -and (Get-Process -Id $p.$_ -ErrorAction SilentlyContinue) }
  if (-not $running) { break }
  Start-Sleep -Milliseconds 300
}
foreach ($name in "audio", "inputs", "clock", "tshark") {
  $id = $p.$name
  if (-not $id) { continue }
  if (Get-Process -Id $id -ErrorAction SilentlyContinue) { Stop-Process -Id $id -Force; Write-Host "force-stopped $name (pid $id)" -ForegroundColor Yellow }
  else { Write-Host "stopped $name cleanly (pid $id)" }
}
Remove-Item (Join-Path $out "STOP") -ErrorAction SilentlyContinue
Rename-Item $pidFile ($pidFile + ".stopped_" + (Get-Date -Format "HHmmss"))
Get-ChildItem $out -File | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 2) } }, LastWriteTime | Format-Table -AutoSize
