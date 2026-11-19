# 18 Nov 2026: plane vs Ostwind in a ground RB custom battle

**Setup:** you in a plane with 2 MGs, Salty in an Ostwind (ground SPAA), private custom battle, ground RB rules.
**Data on disk:** only your PC (`data/20261118/DESKTOP-42SCBR7/`): audio, 85 presses by hand, clock pairing, packet capture (15.5 min).
**Missing:** Salty's audio and input log. Without them, neither "your shot heard on Salty's PC" nor "Salty's shot heard on yours" can be timed.

Scripts: `explore.py` (own shots), `packets.py` (packet timing). Onsets: `data/20261118/DESKTOP-42SCBR7/onsets_all.csv` (`audio_onsets.py --burst-gap-ms 0 --refractory-ms 8`).

## 1. A plane's network runs at 48 Hz even inside a ground battle
Game server 23.111.31.236:20054.

| Direction | This session (plane in ground RB) | 13 Nov (tank in ground RB) | 16 Nov (plane in air RB) |
|---|---|---|---|
| Server → you | **38 /s on a 48.5 Hz grid** (most common gap 20.25 ms, then 40.25 ms) | ≈ 31 /s on a 24.3 Hz grid (gap 41.1 ms) | ≈ 31 /s on a 49.1 Hz grid |
| You → server | **73 /s, 48.000 Hz grid** (gaps 10.25 and 20.25 ms) | 45–49 /s, 24 Hz + 48 Hz harmonic | 59 /s, 48.0 Hz |

- The 48.5 Hz grid holds in all seven 120 s windows (48.51–48.57 Hz). About 40 % of packets sit within ±3 ms of it; the rest are extra packets in between, as before.
- 48.5 is 2 × 24.3, so it looks like the same server send clock as the ground battles, just doubled.
- **So the update rate follows the vehicle you're in, not the game mode.** Being in a plane gets you 48 Hz both ways, even in a ground battle where the tanks run at 24.
- What this can't show: how often the server updates *Salty's tank* inside those packets. A 48 Hz stream can still carry tank positions at 24 Hz.

## 2. Your own gunshot in the plane doesn't wait for a 24 Hz tick
Press → first gunshot onset on your PC, 100–260 ms window: **72 of 85 presses matched**.

| | This session (plane, ground RB) | Plane, air RB (16 Nov) | Tank, ground RB (13 Nov) |
|---|---|---|---|
| Median | **136 ms** | 148 ms | 148–153 ms |
| IQR | **14.8 ms** | 13.3 ms | 21–23 ms |
| 24 Hz sawtooth | **no** | no | yes (Z ≈ 46–92) |

- A 24 Hz wait on its own would spread the delay by an IQR of at least 20.8 ms. The measured 14.8 ms is too tight for that, and removing a 24 Hz wait makes the spread worse (25.1 ms), not better.
- The only phase lock is the game's 21.33 ms sound block (Z = 19 at 46.875 Hz). 24 Hz gives Z = 0.5.
- A 48 Hz wait can't be ruled out: a 48 Hz wait plus the sound block would give an IQR of about 12 ms, close to what we see. With 72 shots the blind frequency scan is just noise.
- The plane is about 12 ms quicker than in the air battle (136 vs 148 ms). The test differs too (hand taps, other server), so treat that as "about the same".

## 3. Things seen but not explained yet
- **A second cluster 350–380 ms after your presses** (about 45 presses), and another at 400–450 ms. These are sounds on *your* PC, so they aren't Salty hearing you. They could be your rounds hitting (impact sounds, which would depend on range) or the hit-confirmation sound. Can't tell without knowing the distance or seeing the screen.
- **Salty's Ostwind as heard on your PC:** 3,110 onsets that aren't yours. The gaps between them are all over the place (20–80 ms clusters), far shorter than a 37 mm gun's rate of fire, so the detector is picking up shell bursts, hits and echoes too. This can't be cleaned up without Salty's press log.
- **The "double-fire" on Salty's PC** that you heard needs Salty's recording. On your own PC, the two MGs fire together: almost every tap gives a single onset.

## 4. Salty's PC (copied from his "Mega Drive Sharing" share into `data/20261118/SALTY/`)
Script: `cross.py` (all times on Salty's clock, offset −883 ms from your PC).

**Your plane's gunfire heard on Salty's PC (in the Ostwind):**
- Salty's recording is noisy: about 8.8 onsets per second in the background. Plain onset matching shows no peak.
- Counting only *loud* events (more than 4× the loudness in the 2 s before your press), **25 of your 81 shots** produced one 200–320 ms after your click: **median 256 ms, IQR 30 ms**. By chance about 5–6 would land in that window, so the cluster is real, but most of your shots couldn't be picked out of the noise.
- Compared with the earlier runs:

| Path | Press → heard on the other PC | Minus the shooter's own sound |
|---|---|---|
| **Plane → Ostwind, ground RB (today)** | **≈ 256 ms** (n = 25) | **≈ 120 ms** |
| Tank → tank, ground RB (13 Nov) | 305–332 ms | 150–180 ms |
| Plane → plane, air RB (16 Nov) | 318 ms | ≈ 170 ms |

- Today's path looks about 30–60 ms quicker. **Caveats:** in-game ping wasn't written down, the in-game sound-travel-delay setting is unknown (if it was on, distance adds delay), and n = 25 is small.
- **The "double-fire":** in 5 shots a second loud event follows the first about 110–140 ms later (250→370, 241→362, 277→390, 278→398, 284→…). That's roughly 3 ticks at 24 Hz (125 ms), but it's too few cases to call. It could just as well be the second MG, an echo or the rounds hitting.

**Salty's Ostwind shots: can't be timed.** His input log has only **20 left-mouse presses**, and none of them is followed by a loud gunshot on his own PC. He most likely fired with a different button or key, which the logger doesn't record by default (only the left mouse button). So the Ostwind tick test is still open.

## Next run
- Salty: start the logger with his real fire key (`-Keys <key>`), or fire with the left mouse button.
- Both: write down the in-game ping, and turn off the sound-travel delay (or keep the distance fixed).
- Fly or park close to the Ostwind so your shots stand out above his engine noise.

## (old) To finish this comparison, copy from Salty's PC
`data/20261118/SALTY/` (or wherever his recorder saved): `audio_Salty_*.wav`, `audio_Salty_*.timing.jsonl` and `inputs_Salty_*.jsonl`.
With those:
- your plane's shots heard on his PC: delay, the share that never arrives, and the double-fire;
- his Ostwind's shots: does the Ostwind wait for a 24 Hz tick on his own PC, and how late do they reach you in the plane?
