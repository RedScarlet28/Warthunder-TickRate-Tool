# Experiment L: Shooting latency by sound (the tick-rate test)

**Idea:** the shooter taps fire on one PC. The other PC records the game sound it plays. Both PCs are clock-paired to **Salty's PC**. For every press we measure

`press on shooter PC → gunshot heard on observer PC`

Each press lands at a random moment, so the "wait for the next tick" part of that delay is spread evenly over one tick period. Over a few hundred presses, the **width of the delay distribution is the tick period**. A second, independent method (phase folding) checks whether the onsets lock to a fixed grid. Both methods are combined into one **verdict**.

The shooter PC also records its *own* gunshot sound. `press → own shot` tests Anton's official **48 Hz ballistic fire grid** directly (Exp. J1 in the main plan).

**Results (13 and 16 Nov 2026):** ground shots wait for a **24 Hz** tick, independent of FPS; air runs at ≈ 48 Hz with no visible fire wait; "10 Hz" is ruled out. See [`analysis/20261113_findings/FINDINGS.md`](analysis/20261113_findings/FINDINGS.md).

Why sound and not video: audio is sampled 48,000 times a second. In validation, onsets were timed with about **0.3 ms** scatter, versus one frame every 7–8 ms in video. No OBS, no flash overlay, no frame-rate artifacts. (The video path in `analyze_shooting.py` still works as a backup.)

## Validated on simulated data (with known truth)
`python synth_audio_test.py` builds real WAV files (engine rumble, gunshot transients, sound-card clock 35 ppm off, OS buffer jitter, simulated 137 fps game frames, 10 ms audio mixer, 3.2 ms clock offset between PCs). It then runs the full pipeline:

| Truth | Verdict | Spread fit | Shooter own-shot grid |
|---|---|---|---|
| 48 Hz shared grid | **20.83 ms** | 21.0 ms | 20.83 ms |
| 10 Hz server tick | **99.99 ms** | 99.5 ms | – |
| 48 Hz client and server on independent grids | **20.83 ms** | 21.0 ms | 20.83 ms |

It detected 250 of 250 shots with no doubles. The audio mixer block was found automatically (10.0 ms), and the clock offset was recovered to about 0.002 ms. (`python synth_test.py` validates the video path the same way.)

## One-time setup (both PCs)
1. Copy the **whole project folder** to Salty's PC (the scripts share `tools/telemetry_logger.py`).
2. Python 3.11+ on both, then: `pip install pyaudiowpatch numpy scipy matplotlib` (Salty's PC only needs `pyaudiowpatch` for recording; the analysis runs on your PC).
3. Both PCs **wired, on the same LAN** if possible. If Salty is remote over the internet, clock pairing still works but is less accurate (asymmetric routes bias it by up to half the ping).
4. Windows sound settings for the playback device on both PCs: turn **off** audio enhancements, spatial sound and loudness equalization.
5. In War Thunder on both PCs: **music 0, voice/radio 0, effects 100 %**. **the same FPS cap on both PCs** (WT offers fixed values only, e.g. 60 or 120). Runs at 120 and 60 FPS both gave 24 Hz on the ground, so either works. Turn **sound travel delay off** so distance doesn't matter.
6. First run on Salty's PC: allow the Windows Firewall prompt for Python on **private** networks (UDP 47123).
7. Find the capture interface number on each PC: `& "C:\Program Files\Wireshark\tshark.exe" -D` (on your PC it's **4**, "Ethernet 3").

## Running a session
**Easiest way: double-click a launcher** in `experiments\shooting_latency`.
- Salty's PC: `START_salty_reference.bat`
- Your PC: `START_my_pc_client.bat`
- When you're done, on both PCs: `STOP_recording.bat`

The window stays open so you can read any errors. The capture interface is picked automatically. The manual commands below do the same thing.

**Salty's PC** (in `experiments\shooting_latency`):
```powershell
.\start_shooting.ps1 -Role reference -Interface <n>
```
It prints Salty's IP address, which should be 192.168.1.225.

**Your PC:**
```powershell
.\start_shooting.ps1 -Role client -Interface 4
```
Salty's IP (**192.168.1.225**) is the default for `-RefIp`. If it ever changes, pass `-RefIp <new IP>`.
The clock window should show `offset … min RTT …` updating every 5 s. On a LAN, min RTT should be well under 1 ms.

**In game:** a custom battle with just your two accounts. Use **ground vehicles parked at a fixed distance** (e.g. 100 m, both stationary). The game probably delays sound with distance, so the distance must not change during a run. A constant offset doesn't affect the tick estimate.

**Protocol (one run ≈ 7 min):**
1. **Shooter** taps the machine gun: one short tap, then wait a *random* 0.6–2 s, repeat. **At least 300 taps.** Never hold fire. Vary the rhythm; don't tap to a beat. **In planes hold each tap for at least 80 ms**: shorter taps often never play on the other PC (see FINDINGS, air run).
2. **Observer** doesn't shoot and doesn't move. Keep the camera steady and let your own engine idle.
3. Swap roles and repeat, so you get both directions.
4. Optional extra runs: the shooter in a plane flying past (sound distance changes, so it's analysed separately), or different server regions.

**Stop on both PCs:**
```powershell
.\stop_shooting.ps1
```
Then copy Salty's `data\<date>\<SALTY-PC-NAME>\` folder to the same place on your PC.

## Analysis (on your PC)
```powershell
python audio_onsets.py data\<date>\<OBSERVER-PC>\audio_<...>.wav --plot     # check the PNG: red lines on every shot?
python audio_onsets.py data\<date>\<SHOOTER-PC>\audio_<...>.wav
python analyze_shooting.py `
  --shooter-inputs  data\<date>\<SHOOTER-PC>\inputs_<...>.jsonl `
  --shooter-clock   data\<date>\<SHOOTER-PC>\clock_<...>.jsonl `      # omit if the shooter IS Salty's PC
  --observer-clock  data\<date>\<OBSERVER-PC>\clock_<...>.jsonl `     # omit if the observer IS Salty's PC
  --observer-wall-onsets data\<date>\<OBSERVER-PC>\audio_<...>.onsets.csv `
  --shooter-wall-onsets  data\<date>\<SHOOTER-PC>\audio_<...>.onsets.csv `
  --observer-game-fps 120 --shooter-game-fps 120 `
  --pcap-shooter  data\<date>\<SHOOTER-PC>\shoot_<...>.pcapng `
  --pcap-observer data\<date>\<OBSERVER-PC>\shoot_<...>.pcapng `
  --out analysis\run1
```
Read `analysis\run1\report.md`. The **VERDICT** line gives the tick period. The status says whether the two independent methods agree (`CONSISTENT`), and the plots show the delay distribution with the fitted model.

If the fire key is on the keyboard, start the logger with `-Keys space` (or your key) and pass `--fire-button space`.

## What the numbers mean
- **Press → heard on observer**: the median delay is the full chain (shooter input → network → server → network → observer game frame → audio mixer → speaker). The **spread** gives the tick.
- **Press → own shot (shooter)**: if WT fires on the 48 Hz grid, this spread is 20.8 ms wide even with zero network involved.
- **Packet layer**: press → next upstream packet (client send cadence), and last downstream packet → sound (how quickly the observer's client turns a packet into sound).

## Auto-fire (optional, private custom battles only)
`START_autofire.bat` (or `python auto_fire.py --key k`) fires for you, so the timing is cleaner than human taps.
- **Setup:** in War Thunder, bind the machine gun to **K**. Start the recorders first.
- **Controls:**
  - **Ctrl+Shift+F8**: start/pause. A high beep means firing, a low beep means paused.
  - **Ctrl+Shift+F9**: quit.
  - The hotkeys work while the game has focus.
- **Gaps:** random 1.0–2.0 s, held 50 ms, stops after 300 presses. Deliberately not a fixed 1.5 s: that is exactly 36 ticks of 24 Hz, so every shot would land at the same point of the cycle and the tick would become invisible.
- **Safety:** it only presses while the War Thunder window is active.
- **Log:** every press goes to `inputs_autofire_<pc>_<time>.jsonl` next to the other recordings. Analyze with `--shooter-inputs <that file> --fire-button autofire`.
- **Instead of a key:** `--mouse` clicks the left mouse button.
- **Risk:** this injects input, so Gaijin's macro rules apply. Use it only in private custom battles with your own accounts, at your own risk.

## Record to a LOCAL folder
Run the recorders from the project folder on that PC's own disk, never from a network share. On 2026-11-13, writing over the network made the audio recorder drop more than 100 chunks. Copy the `data` folder to the other PC afterwards.

## Check the audio device first
The recorder captures the **Windows default output device**. If War Thunder plays sound to a different device (for example a headset set in WT's sound settings), the recording stays empty: Windows loopback only delivers audio while something plays to that device. This happened on Salty's PC on 2026-11-13, where only 6 s were recorded. Run `python audio_recorder.py --list` and start with `-AudioDevice "<the device WT plays to>"`. After the session, the `.wav` should be roughly 11 MB per minute.

## Limits and safety
- Recording is passive: the input logger only *reads* button events, and the audio is the normal loopback of what the PC plays. The optional `auto_fire.py` (above) is the only part that sends input; use it only in private custom battles, and keep its random gaps. Never use it, or any macro, in public matches.
- Other gun sounds (AI, other players) would confuse onset matching. Only use private custom battles with just the two of you.
- If `audio_onsets.py` finds far more onsets than presses, raise `--k` (e.g. 12). If it misses shots, lower `--k` or lower `--hp`.
