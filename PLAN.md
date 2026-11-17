# War Thunder Netcode Experiment: Master Plan

**Goal:** measure War Thunder's real network timing and hit-registration behaviour precisely, using two PCs, packet captures, the official localhost telemetry API, synchronized high-frame-rate video and server replays. Then build a model that explains the "bad hit-reg at jet speed" experience, with numbers.

Read `research/01_RESEARCH_DOSSIER.md` first. It sets out what is already known, what Gaijin claims, and which rates people tend to confuse.

---

## Status (2026-11-16)
Exp. L (shooting latency by sound) is done for ground (3 runs) and air (1 run). Results: `experiments/shooting_latency/analysis/20261113_findings/FINDINGS.md`.

| Hypothesis | Result so far |
|---|---|
| H1: logical tick = 48 Hz, not 10 | **Partly false.** Ground shots run on **24 Hz**; air packets run at ≈ 48 Hz. 10 Hz ruled out. |
| H2: send rate = tick or a fraction | **Supported.** Ground ≈ 24.3 Hz down; air ≈ 49 Hz down, 48 Hz up. |
| H3, H4, H5, H5b, H7, H8, H9 | Not tested yet (need Exp. B/C/E/F). |
| H6: hit confirmation lag | Not tested yet (hit-marker timing is the next experiment). |
| New: short air taps reach the other player less often | ≈ 22 % of the taps the shooter heard never played remotely; 50 % heard for taps under 50 ms (1 run). |

---

## 0. Important: "tick rate" is several different numbers

People argue past each other because WT has at least **seven different rates**. We measure each one separately:

| # | Rate | What it is | How we measure it | Prior |
|---|---|---|---|---|
| R1 | **Server simulation ("logical") rate** | How often the server steps physics | Indirect: quantization of event timings (Exp. B, E), phase-folding | was "very likely 48 Hz". **Measured: ground 24 Hz, air ≈ 48 Hz** |
| R2 | **Server→client send rate (base)** | Packets per second the server sends you | Packet capture (Exp. A) | **Measured: ≈ 24.3 Hz ground, ≈ 49 Hz air** |
| R3 | **Per-object update rate** | How often *a specific other vehicle's* position changes on your screen. Can be lower than R2 for distant or out-of-view objects | Two-PC telemetry staircase (Exp. C) | "far objects compressed or not sent" (official) |
| R4 | **Client→server controls rate** | How often your inputs are sent | Packet capture, upstream direction (Exp. A) | **Measured: 24 + 48 Hz ground (45–49 pps), 48 Hz air (59 pps)** |
| R5 | **Server-replay sample rate** | Position samples in server replays | Parse replay / frame-step (Exp. I) | **10–15 Hz (official)**, likely source of the "10 tick" myth |
| R6 | **Aim-cursor sync rate** | How often your aim point reaches the server | Replay frame-stepping | ">10/s" (official) |
| R7 | **Ballistic timestep** | Shell integration step, shared by client and server. Shots are fired on this grid | Exp. J (tracer quantization) | **48 Hz = 20.83 ms (official, Anton 2017)**. Bullets are linearly interpolated between steps on the client |

And there are **four latency components**, which we also separate:
`total delay = one-way up + server queue (wait for next tick, 0..1 tick) + server processing + one-way down + client render/frame delay`

---

## 1. Hypotheses (each has a pass/fail test)

| ID | Hypothesis | Test |
|---|---|---|
| H1 | Server logical tick R1 = 48 Hz (the same grid as the official ballistic rate), definitely not 10 | Exp. A periodicity + Exp. B quantization (folding at 20.83 ms) |
| H2 | Base send rate R2 equals R1, or an integer fraction of it (48 / 24 / 16 Hz) | Exp. A |
| H3 | Per-object update rate R3 drops with distance / off-screen / object count | Exp. C distance and view sweeps |
| H4 | Other vehicles are **extrapolated** (officially confirmed by Anton). Expected signature: error ≈ 0 in straight flight, grows ~½·a·τ² in manoeuvres, and **overshoots** after reversals. A constant **lag** would instead mean the "interpolation under ~50 ms" hybrid shipped | Exp. C manoeuvre matrix |
| H5 | No shot rewind (officially confirmed). A hit counts only if the projectile meets the target's *server* position. Ghost hits (small spark, no "Hit" cross) ∝ target manoeuvre during the information delay | Exp. E + G |
| H5b | **Target's ping matters as much as the shooter's.** Anton: target 10 ms + shooter 70 ms → ~99 % accuracy. Prediction: false-positive rate rises with (target ping + shooter ping) and is roughly symmetric in the two | Exp. G (add latency to target vs shooter separately) |
| H6 | Server hit confirmation (the "Hit" cross / sight hit-lines) lags the client spark by RTT + 0..1 tick + processing | Exp. B |
| H7 | The in-game PL indicator under-reports real loss (it counts reliable traffic only, per Anton) | Exp. A (packet gaps vs displayed PL) |
| H8 | Desync and ghost shells get worse with jitter, more than with mean ping | Exp. G |
| H9 | Ground: the "killed behind cover" window ≈ the opponent's latency + tick + extrapolation | Exp. F |

---

## 2. Hardware and software setup (Phase 0, ~1 evening)

### 2.1 Hardware
- **PC-A** and **PC-B**, both **wired** Ethernet, same router, each with its own War Thunder account. One account needs **premium** to host custom battles.
- Monitors at the highest refresh rate available. Turn VRR off for test sessions (fixed frame timing is easier to analyse).
- **External high-speed camera.** A phone in 240 fps slow-motion mode, on a tripod, filming **both monitors at once**. This is the single shared timebase and the strongest timing evidence we can get.
- Optional: an LED or the flash page (tools/sync_flash.html) shown on both screens for sync marks.

### 2.2 Software (both PCs)
| Tool | Purpose | Notes |
|---|---|---|
| **Wireshark + Npcap** (includes `tshark`) | Packet capture | <https://www.wireshark.org/download.html>. Passive, safe with EAC. |
| **Python 3.11+** with `numpy matplotlib pandas opencv-python requests` | Analysis tools | `pip install -r tools/requirements.txt` |
| **OBS Studio** | Screen recording at a fixed 120 or 144 fps, CQP/lossless-ish, with a ms clock overlay | Add the "Browser" source → `tools/sync_flash.html` in a corner |
| **Meinberg NTP** *or* Windows `w32tm` tuned | Clock sync between PCs to ~1 ms | See §2.3 |
| **PingPlotter / `mtr`-style tool** (optional) | Route and jitter to the game server during captures | Use the server IP from the capture |
| **clumsy** (optional, **custom battles only**) | Controlled latency/loss/jitter | <https://jagt.github.io/clumsy/>. Never in public matches. |

### 2.3 Clock synchronization (critical)
1. Make PC-A the time master. Install Meinberg NTP on both (or configure `w32tm`). PC-B syncs to PC-A over the LAN. Check `w32tm /stripchart /computer:PC-A /samples:20` → offset should be < 1–2 ms.
2. Both PCs still sync to the same public NTP pool every hour, which removes drift relative to the server.
3. **Video cross-check:** at the start and end of each session, open `tools/sync_flash.html` full-screen on both PCs and film both screens with the 240 fps camera. The flashes are tied to system time, so any frame offset between them is the residual clock error. Write it in the session log.
4. All tools log **UTC wall-clock with µs precision** (`GetSystemTimePreciseAsFileTime`. Note that plain `time.time_ns()` on Python 3.12/Windows moves in 15.6 ms steps) plus a monotonic QPC clock. pcap timestamps from Npcap are already high-precision.
5. **Timer health check on both PCs.** Anton says ~20 % of PCs have a broken high-precision timer that falls back to ~10 ms precision. Before session 1, run `python -c "import time;print(time.get_clock_info('perf_counter'), time.get_clock_info('time'))"`: perf_counter resolution should be ≤ 1 µs. Also check `bcdedit /enum | findstr /i "useplatformclock"`. It should not be set unless you know why. Both games and our tools depend on this.

### 2.4 Game settings (fixed for all sessions)
- Same graphics preset on both PCs. FPS cap set to a stable value (e.g. 141 on 144 Hz). Note the exact client version.
- Turn on the network indicators (ping / PL / FPS) so they show in video.
- Hit indicator / hit camera enabled.
- Record the server region (chosen in the client).

### 2.5 Folder discipline
```
data/
  session_YYYYMMDD_NN/
    session_log.md          <- copy of templates/session_log.md, filled in
    pcA/  pcap/  telemetry/  obs/  replays/
    pcB/  pcap/  telemetry/  obs/  replays/
    camera/                 <- 240 fps external video
    server_replay/          <- downloaded from warthunder.com battle log
analysis/                   <- outputs of tools/*.py (plots, csv, json)
report/                     <- final write-up
```
`tools/new_session.ps1` creates this structure.

---

## 3. Experiments

Each experiment lists: **setup → procedure → recorded data → analysis → output.** Run them in this order. A gives the baseline that everything else depends on.

### Exp. A: Packet cadence and size (passive, no second player needed) ★ first
**Goal:** R2, R4, jitter, burst structure, true loss proxy (H1, H2, H7).

1. Start `tools/capture_packets.ps1` (UDP only, ring buffer) on PC-A **before** launching WT.
2. Record 3 min of each state. Mark state changes with the telemetry logger's marker key, or write the wall time in the session log:
   - A1 hangar idle · A2 loading screen · A3 Test Flight (single-player, which may still be server-hosted, worth checking) · A4 Air RB match, alone far from others · A5 Air RB in a furball (many planes near) · A6 Ground RB match · A7 Naval (optional) · A8 custom battle with PC-B only.
3. Within A4/A5: 30 s looking at enemies, 30 s looking away / at the sky (interest management test).

**Analysis (`tools/analyze_pcap.py`):**
- Find the game-server UDP flow automatically (largest remote UDP flow).
- Packets/s and bytes/s per direction over time.
- **Inter-arrival histogram**. Peaks at 1/R2 and its multiples. A comb with 20.8 ms spacing → 48 Hz, 33.3 ms → 30 Hz, 100 ms → 10 Hz.
- **Spectrum / phase-folding** of arrival times to find the dominant period. Rayleigh-test score per candidate frequency 5–130 Hz.
- Packet-size distribution vs number of nearby objects (size growing with objects but rate fixed → fixed-rate snapshots).
- Gap detection: inter-arrivals > 3× the median period = probable loss or late burst. Compare with the in-game PL shown in OBS (H7).
- Upstream (client→server) rate and redundancy: are upstream packets sent at 2× the downstream rate?

**Output:** R2 and R4 with confidence intervals, jitter (p50/p95/p99 inter-arrival deviation), whether rates change by mode or object count.

### Exp. B: Server hit-confirmation latency (one PC, AI targets) ★
**Goal:** split total latency into RTT + tick wait + processing. Estimate R1 from quantization (H1, H6).

**Setup:** Test Flight or a custom battle with AI bombers flying straight and level (easy, repeatable hits). Fixed gun (one weapon type), tracers on.
1. Record OBS at 144 fps, plus the 240 fps camera on the monitor, with the ms clock visible.
2. Fire short bursts (2–5 rounds) at the target. 100+ bursts at each of 3 ranges (200 / 500 / 1000 m).
3. Telemetry logger running (hudmsg captures damage/kill events with timestamps).

**Analysis (`tools/video_event_timer.py`):**
- ROI 1: the muzzle/tracer area → frame of trigger pull (first muzzle flash).
- ROI 2: the target spark → client-side hit time.
- ROI 3: the gunsight hit-lines / **"Hit" animated cross** region → **server-confirmed hit time**. (Small sparks are client-only. Big 30 mm+ sparks are server-replicated, so with ≥ 30 mm guns the big-spark onset is a second server signal.)
- Δ = server-confirm − client-spark. Subtract the measured RTT (from capture or overlay ping) → the remainder = tick wait + processing + render.
- **Quantization test:** the residuals should be spread uniformly over [0, 1 tick]. The spread width ≈ the tick period. Also fold the server-confirm timestamps modulo candidate periods. If the server ticks at fixed phase, the folded histogram peaks at the true period. Cross-check against the downstream packet phase from Exp. A (confirm packets should arrive on the same packet cadence).

**Output:** server confirm delay distribution, an R1 estimate, processing overhead.

### Exp. C: Two-PC position truth: how wrong is "where you see him"? ★★ core experiment
**Goal:** R3 (per-object update rate) and the extrapolation error under manoeuvre (H3, H4).

**Setup:** private custom battle, Air, PC-A (target) and PC-B (observer) only, same aircraft type, clear weather, a map with known size. Clocks synced (§2.3). Both run `tools/telemetry_logger.py --hz 100` (own state + `map_obj.json` + `map_info.json`), OBS, and `capture_packets.ps1`.

**Ground truth:** PC-A's own position comes from A's client. That is A's predicted state, which equals the server state except during corrections. **Observed position:** A's position in PC-B's `map_obj.json`. Converted to metres via `map_info.json` and compared at identical wall-clock times (`tools/compare_tracks.py`). The server replay is a third, 10–15 Hz reference.

> ⚠ First calibration step (C0): check how often `map_obj.json` itself refreshes and how precise it is. PC-A looks at its *own* icon (should change every frame). If the minimap API is too coarse, fall back to the video method (C-video below).

**Manoeuvre matrix (PC-A flies, PC-B holds a steady observing position):**

| Run | Manoeuvre | Expected under H4 |
|---|---|---|
| C1 | Straight and level, constant speed (300 / 600 / 900 / 1200 km/h) | error ≈ 0 (extrapolation is perfect) |
| C2 | Constant-rate level turn (3g, 6g, 9g) | constant offset ∝ g·t² |
| C3 | Turn reversals every 3 s (roll left↔right) | error spikes after each reversal, decaying over ~(RTT/2 + update interval) |
| C4 | Snap pull from 1g to max g | single large spike → measures the full extrapolation horizon |
| C5 | Throttle cut / airbrake at constant heading | along-track error from deceleration |
| C6 | Distance sweep: repeat C1+C3 at 0.5 / 1 / 2 / 5 / 10 / 20 km | **R3 vs distance** (staircase step length) |
| C7 | View sweep: PC-B looks at A / looks 180° away / A behind terrain | R3 vs view and occlusion (interest management) |
| C8 | Head-on merge at combined 2000 km/h | worst case for timing; compare A's and B's video of the pass |

**Analysis:**
- **Staircase detection:** in B's track of A, find the instants where the position changes discontinuously, or where velocity is re-estimated. Their spacing distribution is R3. Plot R3 vs distance and view.
- **Error time series** `e(t) = |pos_B_sees_A(t) − pos_A_self(t)|`. Regress e against A's lateral acceleration (from A's telemetry `Ny`, turn rate). Fit `e ≈ ½·a·τ²` → **τ = the effective extrapolation horizon**. Compare τ with (one-way A→server + server tick + server→B one-way + R3 interval).
- Check whether B's display **leads** or **lags** A's truth. Extrapolation overshoots on reversals. Interpolation lags constantly.

**C-video fallback:** PC-B keeps A in the gunsight at a fixed range. The 240 fps camera films both monitors. Mark A's wing-rock events on A's screen (own aircraft) and on B's screen (seen aircraft). Δt per event = visual latency. Frame-step to see the staircase directly (A's model "jumps").

**Output:** R3(distance, view), τ, a chart of error in metres vs manoeuvre and speed. This chart is what directly explains the jet-speed complaint.

### Exp. D: Mutual-view comparison (what each player sees during the same second)
Same session as C. Both record OBS. Run tight formation, scissors and overshoot scenarios. Put the two videos side by side, synced via the flash marks, together with the server replay (third viewpoint). Output: an annotated side-by-side video for the report. Good for showing results; its numeric value is secondary.

### Exp. E: Controlled hit-registration grid ★★
**Goal:** false-positive "spark but no damage" rate and ghost-hit rate vs conditions (H5).

**Setup:** private custom battle. PC-A is the target with a **known flight program**. PC-B is the shooter with a fixed gun and belt. Both log telemetry. A's damage log (hudmsg on A) and the server replay are the truth.

**Matrix (at least 50 bursts per cell, more if you can):**
- Target state: straight / steady turn / jinking (C3 pattern)
- Range: 200 / 400 / 800 m
- Aspect: 6 o'clock (low deflection) / 30° / 60°+ deflection
- Speed band: 400 / 800 / 1100 km/h

**For each burst record:** client sparks seen on B (video ROI), server hit-lines on B, damage events on A (hudmsg), damage visible in the server replay.

**Classify each burst:** TP (spark + server hit), FP-ghost (spark, no server hit), FN (no spark but server hit / damage on A), TN.

**Analysis:** FP rate vs target lateral acceleration × (B's ping + τ). H5 predicts FP ≈ 0 for straight targets and rising steeply with manoeuvre and deflection. Logistic regression on: target accel, deflection, range, ping, jitter.

**Output:** a hit-reg reliability map. Each cell gives "probability that a visual hit is real".

### Exp. F: Ground combat timing (tanks)
- **F1 Peeker's advantage:** A peeks a corner at fixed speed. B holds an angle. Measure, on both videos, when A becomes visible on B vs A's own view. Gives the peeker's time advantage in ms.
- **F2 Killed behind cover:** A drives into cover at a known moment. B fires just before or after. Measure the A-side delay between "fully behind cover on my screen" and the kill.
- **F3 Turret/stabilizer snapping at range:** B observes A's turret traverse at 200 / 1000 / 2000 m. Frame-step for update intervals (R3 for ground objects).
- **F4 Shell flight:** A is stationary. B fires at 1000 / 2000 m. Compare impact time on B's screen vs damage time on A.

### Exp. G: Network-condition sweep (custom battle only, optional, your own risk)
Use **clumsy** on one PC at a time: added latency 0 / 50 / 100 / 200 ms, jitter ±0 / ±30 ms, loss 0 / 2 / 5 %. Repeat a reduced Exp. E (straight and jinking at 400 m) and Exp. C3.
- **H5b test:** add latency to the **target only**, then the **shooter only**, with the same amounts. Anton's model predicts both raise FP-ghosts, roughly symmetrically, because the information delay = target uplink + server + shooter downlink. A strongly asymmetric result would mean the real implementation differs from the 2017 description.
- Jitter vs mean latency at equal means (H8). Anton claims jitter is worse.

### Exp. H: Server and environment factors
- Repeat A and a reduced C on 2–3 server regions (EU / NA / Asia) and at peak vs off-peak hours.
- Record the server IP from the capture each time. Track route and jitter with PingPlotter.
- Look for **server-side hitches**: periods where downstream inter-arrivals stretch for all clients at once (PC-A and PC-B in the same match). That would mean the server is overloaded, not the network.

### Exp. I: Replay forensics
- Download the **server replay** for every custom battle session.
- Frame-step positions: confirm the 10–15 Hz sample rate (R5) and that it differs from R2/R3. *This is the main evidence for the "10 tick myth" explanation.*
- Compare client replay vs server replay positions for the same moment.
- (Optional) Look into the community `.wrpl` parsers. Use them only with files you own, and run them sandboxed.

### Exp. J: Verify the official 48 Hz ballistic grid
Anton (2017): bullets are stepped at 48 Hz on client and server, fired on that grid, and linearly interpolated in between on the client.
- **J1 (fire-time quantization):** at 144 fps, fire single shots (or the first round of bursts) at random moments. Measure trigger-press → first muzzle flash frame. If shots wait for the next 48 Hz tick, the delay is spread uniformly over 0–20.8 ms on top of a constant.
- **J2 (trajectory kinks):** a slow-moving tracer seen side-on, frame-stepped at 144 fps. Linear interpolation between 48 Hz points shows as **tiny direction changes every 20.83 ms** along the curved trajectory. Compare FPS caps of 60 and 144: the kink spacing must stay at 20.83 ms.
- J1 and J2 also anchor the phase of the 48 Hz grid, which Exp. B folds against.

### Exp. L: Shooting latency by sound ★★★ (the most direct tick-rate test)
Self-contained in [`experiments/shooting_latency/`](experiments/shooting_latency/README.md). The shooter taps fire at random moments, and the observer PC records its game sound. Both PCs are clock-paired to Salty's PC (reference). The spread of `press → gunshot heard` over 300+ taps gives the tick period, and phase folding confirms it. The shooter's own gunshot sound tests the official 48 Hz fire grid. Validated on simulated data: it recovered 48 Hz / 10 Hz exactly, with about 0.3 ms onset precision. **Done:** ground 24 Hz (runs 1–3), air run on 16 Nov.

### Exp. K: Recon of the game files (offline, no game running)
- Look in your WT install and the public **War-Thunder-Datamine** (`github.com/gszabi99/War-Thunder-Datamine`) for network/physics settings blocks (`tickrate`, `physFps`, `netUpdate`, `sendRate`, `interp`, `extrap`) in `config.blk` and the unpacked `*.vromfs` blk files. Only read text config. Do not modify anything.

---

## 4. Statistics and rigour
- **Sample sizes:** ≥ 100 events per condition for latency distributions. ≥ 50 bursts per hit-reg cell. Repeat every key experiment on ≥ 2 different days.
- Report **medians and p95/p99**, not just means. Network delay distributions are skewed.
- **Period estimation:** use phase-folding (Rayleigh Z) and the inter-arrival comb together, and require them to agree. Give a bootstrap CI.
- **Blind classification:** for Exp. E, label sparks and hit-lines from video *before* looking at A's damage log.
- **Version pinning:** record the client version for every session. A patch mid-experiment means you restart the comparison set.
- **Controls:** run every network experiment at least once in a baseline state (hangar, Test Flight) to separate client effects from server effects.

---

## 5. Timeline

| Day | Work |
|---|---|
| 1 | Phase 0 setup, clock sync, tool smoke tests (`telemetry_logger --selftest`, one capture) |
| 2 | Exp. A all states + Exp. K recon → first R2/R4 answer |
| 3 | Exp. B (single PC) → server confirm latency and R1 estimate |
| 4–5 | Exp. C + D (two PCs) → R3, τ, error charts |
| 6–7 | Exp. E hit-reg grid (the long one) |
| 8 | Exp. F ground, Exp. I replays |
| 9 | Exp. G and H (optional) |
| 10 | Analysis, report, publishable charts and side-by-side video |

---

## 6. Final deliverables
1. **Measured table of R1–R7** with confidence intervals. This alone settles the "10 tick" debate.
2. **Latency budget breakdown** (up / tick wait / processing / down / render) for hit confirmation.
3. **Extrapolation error chart**: metres of position error vs target g-load and speed, overlaid with aircraft wingspan.
4. **Hit-reg reliability map** from Exp. E.
5. **Annotated side-by-side videos** of the same engagement from both PCs plus the server replay.
6. A report written for the WT forum / Reddit, citing the official statements in the dossier and placing the measured numbers against them.

---

## 7. Open items for you
- [x] Anton's 2017 post saved (`research/raw/anton_reddit_2017.md`): officially confirms the extrapolation model, no shot rewind, and 48 Hz ballistics.
- [ ] (Optional) top comments of the "10 tic" thread, in case anyone posted capture numbers.
- [ ] Timer health check on both PCs (§2.3 step 5).
- [x] Custom battles hosted (13 and 16 Nov).
- [x] Install Wireshark/Npcap and Python on both PCs (OBS not needed for Exp. L).
- [ ] Tell me the monitors' refresh rates and the phone's slow-mo fps so I can tune the tool defaults.
