<#
.SYNOPSIS
  Start ALL recorders for a session as independent background processes, so closing
  terminal tabs/windows cannot kill them:
    1. tshark packet capture (minimized window)
    2. telemetry_logger.py (minimized window)
    3. mark_hotkeys.py with a live health check (visible window; beeps a WARNING if
       the capture or telemetry file stops growing)
  PIDs are saved to <session>\recording_pids.json. Stop everything with stop_recording.ps1.

.EXAMPLE
  .\tools\start_recording.ps1                     # newest data\session_*, PC-A, interface 4
  .\tools\start_recording.ps1 -Session data\session_20261113_02 -Pc pcB -Interface 3
#>
param(
  [string]$Session = "",
  [string]$Pc = "pcA",
  [string]$Interface = "4",
  [int]$Hz = 100
)
$root = Split-Path $PSScriptRoot -Parent
if (-not $Session) {
  $Session = (Get-ChildItem (Join-Path $root "data") -Directory -Filter "session_*" | Sort-Object Name | Select-Object -Last 1).FullName
}
$Session = (Resolve-Path $Session).Path
$pidFile = Join-Path $Session "recording_pids.json"
if (Test-Path $pidFile) {
  $old = Get-Content $pidFile -Raw | ConvertFrom-Json
  $alive = @($old.tshark, $old.logger, $old.hotkeys) | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
  if ($alive) { Write-Warning "Recording already running for this session (PIDs $($alive -join ', ')). Run stop_recording.ps1 first."; exit 1 }
}
$pcapDir = Join-Path $Session "$Pc\pcap"; $telDir = Join-Path $Session "$Pc\telemetry"
New-Item -ItemType Directory -Force -Path $pcapDir, $telDir | Out-Null

$tshark = @("$env:ProgramFiles\Wireshark\tshark.exe", "${env:ProgramFiles(x86)}\Wireshark\tshark.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tshark) { Write-Error "tshark not found"; exit 1 }
$python = (Get-Command python -ErrorAction Stop).Source

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$pcapFile = Join-Path $pcapDir ("wt_{0}_{1}.pcapng" -f $env:COMPUTERNAME, $stamp)
$filter = "udp and not port 53 and not port 5353 and not port 1900 and not port 137 and not port 138 and not port 67 and not port 68 and not port 123"
"start_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Out-File -Encoding utf8 (Join-Path $pcapDir "capture_meta_$stamp.txt")
(w32tm /query /status 2>$null) | Out-File -Append -Encoding utf8 (Join-Path $pcapDir "capture_meta_$stamp.txt")

$t = Start-Process -FilePath $tshark -PassThru -WindowStyle Minimized -ArgumentList @(
  "-i", $Interface, "-f", "`"$filter`"", "-s", "96", "-B", "64", "-b", "filesize:204800", "-w", "`"$pcapFile`"")
$l = Start-Process -FilePath $python -PassThru -WindowStyle Minimized -ArgumentList @(
  "`"$root\tools\telemetry_logger.py`"", "--hz", $Hz, "--out", "`"$telDir`"")
$h = Start-Process -FilePath $python -PassThru -WindowStyle Normal -ArgumentList @(
  "`"$root\tools\mark_hotkeys.py`"", "--out", "`"$telDir`"", "--watch-pcap", "`"$pcapDir`"", "--watch-telemetry", "`"$telDir`"")

@{ tshark = $t.Id; logger = $l.Id; hotkeys = $h.Id; started = (Get-Date).ToString("o"); pcap = $pcapFile } |
  ConvertTo-Json | Out-File -Encoding utf8 $pidFile

Start-Sleep -Seconds 4
$ok = $true
foreach ($p in @(@("tshark", $t), @("logger", $l), @("hotkeys", $h))) {
  $alive = Get-Process -Id $p[1].Id -ErrorAction SilentlyContinue
  if ($alive) { Write-Host ("[OK ] {0,-8} pid {1}" -f $p[0], $p[1].Id) } else { Write-Host ("[ERR] {0,-8} exited immediately" -f $p[0]) -ForegroundColor Red; $ok = $false }
}
Write-Host "`nSession: $Session"
if ($ok) { Write-Host "All recorders running. You can close this window. Stop with: .\tools\stop_recording.ps1" -ForegroundColor Green }
