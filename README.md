# War Thunder Netcode Experiment

Measuring War Thunder's real server timing, update rates and hit-registration behaviour with two PCs, passive packet capture, the official localhost telemetry API (port 8111), synchronized high-frame-rate video and server replays.

## Results so far
**[experiments/shooting_latency/analysis/20261113_findings/FINDINGS.md](experiments/shooting_latency/analysis/20261113_findings/FINDINGS.md)**: ground vehicles fire on a 24 Hz tick (FPS-independent), air runs at ≈ 48 Hz, "10 Hz" is ruled out, and short air taps often never reach the other player.

## Start here
1. **[research/01_RESEARCH_DOSSIER.md](research/01_RESEARCH_DOSSIER.md)**: everything Gaijin has officially said, community claims, and what Gaijin's open-source Dagor Engine code shows (tick-rate constants, lag compensation, interpolation).
2. **[PLAN.md](PLAN.md)**: the full experiment plan: the 7 different "rates", hypotheses H1–H9, experiments A–K, statistics, timeline, deliverables.

## Layout
```
PLAN.md                         master experiment plan
research/01_RESEARCH_DOSSIER.md sourced findings (official / source code / community)
research/raw/                   paste primary sources here (e.g. Anton's 2017 Reddit post)
reference/dagor_engine_netcode_src/  copies of the relevant DagorEngine files (Gaijin, BSD-3)
tools/
  telemetry_logger.py   polls 127.0.0.1:8111 at up to ~100 Hz -> JSONL with ns timestamps
  capture_packets.ps1   passive tshark UDP header capture (ring buffer + clock metadata)
  analyze_pcap.py       game-flow detection, send rates, inter-arrival comb, Rayleigh periodicity, gaps
  compare_tracks.py     Exp. C: where A is vs where B sees A -> per-object update rate, error, tau
  video_event_timer.py  frame-accurate onset detection in ROIs (muzzle / spark / server hit-lines)
  sync_flash.html       clock + flash + binary-second page for filming both screens (clock sync check)
  new_session.ps1       creates data/session_YYYYMMDD_NN/ with the standard layout + log
templates/session_log.md
data/  analysis/  report/
```

## Quick start (each PC)
```powershell
pip install -r tools\requirements.txt
.\tools\new_session.ps1                      # creates data\session_YYYYMMDD_NN
.\tools\start_recording.ps1                  # capture + telemetry + hotkeys, as detached processes
#   ... play; Ctrl+Shift+1..9/0/M = markers (high beep = OK, three low beeps = recording problem)
.\tools\stop_recording.ps1                   # stops everything, lists what was captured
python -I tools\analyze_pcap.py data\session_...\pcA\pcap\<file>.pcapng --out analysis\session_...\pcA --windows 30
```
On PC-B: `.\tools\start_recording.ps1 -Pc pcB -Interface <n>` (list interfaces with `.\tools\capture_packets.ps1 -ListInterfaces`).
The recorders don't depend on any terminal window, so closing windows or tabs can't stop them.

## Ground rules
Passive observation only: no memory reading, injection or client modification (Easy Anti-Cheat). No latency/loss injection in public matches. See the dossier §5.

## What is in this repository
The source, documentation, analysis outputs and packet captures (`.pcapng`) are versioned here.

Raw recordings are **not** in git — they are 100–250 MB per `.wav` and the edit folder alone is ~39 GB. That covers:

- `video/` (renders, edit media, stems)
- raw `*.wav` audio recordings
- raw `*.jsonl` telemetry and marker logs

Derived results (`.onsets.csv`, `.csv`, `summary.json`, figures) are committed, so every published number can be traced back. Raw captures are published as release assets where needed; see the Releases page.
