<#
.SYNOPSIS
  Start all recorders for the shooting-latency experiment as detached background processes.

  Salty's PC  (reference clock):  .\start_shooting.ps1 -Role reference -Interface <n>
  Other PC    (paired to Salty):  .\start_shooting.ps1 -Role client -Interface <n>
                                  (-RefIp defaults to Salty's PC, 192.168.1.225)

  Each PC records:
    - clock_sync.py   (serve on Salty's PC / client on the other PC)
    - input_logger.py (fire-button presses; mouse buttons + optional -Keys)
    - audio_recorder.py (loopback = the game sound this PC plays)
    - tshark packet capture (headers only)
  Output: experiments\shooting_latency\data\<Session>\<host>\...   Stop with .\stop_shooting.ps1

.EXAMPLE
  .\start_shooting.ps1 -Role reference -Interface 4
  .\start_shooting.ps1 -Role client -RefIp 192.168.1.50 -Interface 4 -Keys space
#>
param(
  [ValidateSet("", "reference", "client")][string]$Role = "",
  [string]$RefIp = "192.168.1.225",   # Salty's PC
  [string]$Interface = "",
  [string]$Session = (Get-Date -Format "yyyyMMdd"),
  [string]$Keys = "",
  [string]$AudioDevice = ""
)
$here = $PSScriptRoot
if (-not $Role) {
  Write-Host "Which PC is this?"
  Write-Host "  1 = Salty's PC (reference clock)"
  Write-Host "  2 = the other PC (client, pairs to $RefIp)"
  $choice = Read-Host "Type 1 or 2"
  if ($choice -eq "1") { $Role = "reference" } elseif ($choice -eq "2") { $Role = "client" }
  else { Write-Host "Unknown choice '$choice'." -ForegroundColor Red; exit 1 }
}
if ($Role -eq "client" -and -not $RefIp) { Write-Host "-RefIp <Salty's PC IP> is required for -Role client" -ForegroundColor Red; exit 1 }
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { Write-Host "Python not found on PATH. Install Python 3.11+ (tick 'Add to PATH')." -ForegroundColor Red; exit 1 }
$python = $pyCmd.Source

# Auto-pick the capture interface: the adapter that carries the default route (= internet traffic).
function Find-CaptureInterface {
  $tsharkExe = @("$env:ProgramFiles\Wireshark\tshark.exe", "${env:ProgramFiles(x86)}\Wireshark\tshark.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $tsharkExe) { return "" }
  $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
  if (-not $route) { return "" }
  $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
  if (-not $adapter) { return "" }
  $guid = $adapter.InterfaceGuid.Trim("{}")
  $line = & $tsharkExe -D 2>$null | Where-Object { $_ -match [regex]::Escape($guid) } | Select-Object -First 1
  if ($line -match '^(\d+)\.') { Write-Host "Capture interface: $line"; return $Matches[1] }
  return ""
}
if (-not $Interface) { $Interface = Find-CaptureInterface }
& $python -c "import pyaudiowpatch" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Missing audio library. Run:  pip install pyaudiowpatch" -ForegroundColor Red; exit 1 }

$out = Join-Path $here ("data\{0}\{1}" -f $Session, $env:COMPUTERNAME)
New-Item -ItemType Directory -Force -Path $out | Out-Null
Remove-Item (Join-Path $out "STOP") -ErrorAction SilentlyContinue   # stale stop flag from a previous run
$pidFile = Join-Path $out "shooting_pids.json"
if (Test-Path $pidFile) {
  $old = Get-Content $pidFile -Raw | ConvertFrom-Json
  $alive = $old.PSObject.Properties.Value | Where-Object { $_ -is [int] -or $_ -is [long] } | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
  if ($alive) { Write-Warning "Already running (PIDs $($alive -join ', ')). Run .\stop_shooting.ps1 first."; exit 1 }
}

$procs = [ordered]@{}
if ($Role -eq "reference") {
  $procs.clock = Start-Process $python -PassThru -WindowStyle Normal -ArgumentList @("`"$here\clock_sync.py`"", "serve")
} else {
  $procs.clock = Start-Process $python -PassThru -WindowStyle Normal -ArgumentList @("`"$here\clock_sync.py`"", "client", "--ref", $RefIp, "--out", "`"$out`"")
}
$inArgs = @("`"$here\input_logger.py`"", "--out", "`"$out`"")
if ($Keys) { $inArgs += @("--keys", $Keys) }
$procs.inputs = Start-Process $python -PassThru -WindowStyle Minimized -ArgumentList $inArgs
$auArgs = @("`"$here\audio_recorder.py`"", "--out", "`"$out`"")
if ($AudioDevice) { $auArgs += @("--device", "`"$AudioDevice`"") }
$procs.audio = Start-Process $python -PassThru -WindowStyle Minimized -ArgumentList $auArgs

if ($Interface) {
  $tshark = @("$env:ProgramFiles\Wireshark\tshark.exe", "${env:ProgramFiles(x86)}\Wireshark\tshark.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($tshark) {
    $pcap = Join-Path $out ("shoot_{0}_{1}.pcapng" -f $env:COMPUTERNAME, (Get-Date -Format "HHmmss"))
    $filter = "udp and not port 53 and not port 5353 and not port 1900 and not port 137 and not port 138 and not port 67 and not port 68 and not port 123"
    $procs.tshark = Start-Process $tshark -PassThru -WindowStyle Minimized -ArgumentList @("-i", $Interface, "-f", "`"$filter`"", "-s", "96", "-B", "64", "-w", "`"$pcap`"")
  } else { Write-Warning "tshark not found - no packet capture" }
} else { Write-Warning "No -Interface given - no packet capture (list with: & 'C:\Program Files\Wireshark\tshark.exe' -D)" }

$ids = [ordered]@{ role = $Role; started = (Get-Date).ToString("o") }
foreach ($k in $procs.Keys) { $ids[$k] = $procs[$k].Id }
$ids | ConvertTo-Json | Out-File -Encoding utf8 $pidFile

Start-Sleep -Seconds 4
$ok = $true
foreach ($k in $procs.Keys) {
  if (Get-Process -Id $procs[$k].Id -ErrorAction SilentlyContinue) { Write-Host ("[OK ] {0,-7} pid {1}" -f $k, $procs[$k].Id) }
  else { Write-Host ("[ERR] {0,-7} exited immediately" -f $k) -ForegroundColor Red; $ok = $false }
}
Write-Host "`nOutput: $out"
if ($Role -eq "reference") {
  $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in "Dhcp", "Manual" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress
  Write-Host "Salty's PC is the reference clock. Give the other PC this IP:  $ip" -ForegroundColor Cyan
}
if ($ok) { Write-Host "All recorders running. Stop with .\stop_shooting.ps1 -Session $Session" -ForegroundColor Green }
