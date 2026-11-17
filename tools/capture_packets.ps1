<#
.SYNOPSIS
  Passive UDP packet capture for War Thunder netcode analysis (tshark / Npcap).
  Captures headers only (snaplen 96) - we analyse timing/size/direction, never content.

.EXAMPLE
  .\tools\capture_packets.ps1 -ListInterfaces
  .\tools\capture_packets.ps1 -Interface 4 -OutDir data\session_20261114_01\pcA\pcap
  .\tools\capture_packets.ps1 -Interface "Ethernet" -OutDir ... -DurationMin 30

  Start BEFORE launching the game, stop with Ctrl+C. Run from an elevated shell if
  Npcap was installed with "admin-only" mode.
#>
param(
  [string]$Interface = "",
  [string]$OutDir = ".\pcap_out",
  [int]$DurationMin = 0,          # 0 = until Ctrl+C
  [int]$RingFileMB = 200,
  [switch]$ListInterfaces
)

$tshark = @("$env:ProgramFiles\Wireshark\tshark.exe", "${env:ProgramFiles(x86)}\Wireshark\tshark.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tshark) { Write-Error "tshark not found - install Wireshark + Npcap"; exit 1 }

if ($ListInterfaces -or -not $Interface) {
  & $tshark -D
  if (-not $Interface) { Write-Host "`nRe-run with -Interface <number or name> (pick your wired Ethernet)."; }
  exit 0
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$file = Join-Path $OutDir ("wt_{0}_{1}.pcapng" -f $env:COMPUTERNAME, $stamp)

# UDP only; exclude obvious LAN noise (mDNS, SSDP, NetBIOS, DHCP, DNS, NTP keeps for reference? -> excluded)
$filter = "udp and not port 53 and not port 5353 and not port 1900 and not port 137 and not port 138 and not port 67 and not port 68 and not port 123"

$targs = @("-i", $Interface, "-f", $filter, "-s", "96", "-B", "64",
          "-b", "filesize:$($RingFileMB*1024)", "-w", $file)
if ($DurationMin -gt 0) { $targs += @("-a", "duration:$($DurationMin*60)") }

# Log the wall-clock + NTP status at start so captures can be aligned with telemetry/video
$meta = Join-Path $OutDir ("capture_meta_{0}_{1}.txt" -f $env:COMPUTERNAME, $stamp)
"start_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Out-File -Encoding utf8 $meta
(w32tm /query /status 2>$null) | Out-File -Append -Encoding utf8 $meta

Write-Host "Capturing on '$Interface' -> $file  (Ctrl+C to stop)"
& $tshark @targs
"stop_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Out-File -Append -Encoding utf8 $meta
