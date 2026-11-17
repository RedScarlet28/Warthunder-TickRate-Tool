# War Thunder Netcode: Research Dossier

Compiled 2026-11-13, updated 2026-11-16 with our own measurements (tagged **[MEASURED]**, details in `experiments/shooting_latency/analysis/20261113_findings/FINDINGS.md`). This file covers what Gaijin has officially said, what the community claims, and what Gaijin's open-source Dagor Engine code shows. Every claim is tagged:

- **[OFFICIAL]**: Gaijin wrote or said it.
- **[SOURCE CODE]**: from Gaijin's public DagorEngine repository. Same engine family as War Thunder, but **not WT's own game code** (see §3).
- **[COMMUNITY]**: players' claims, not verified.
- **[INFERENCE]**: our own reasoning. The experiment has to test it.
- **[MEASURED]**: what our two-PC recordings showed (13 and 16 Nov 2026).

---

## 1. Official Gaijin statements

### 1.1 "Vehicle Collision Physics in game – An explanation", Anton Yudintsev (CEO / lead dev), 29 Apr 2016 [OFFICIAL]
<https://warthunder.com/en/news/4116--en>

This is the most important official description of the netcode model. In short:

1. The client applies your controls locally, simulates physics and **sends controls (not positions) to the server**.
2. The server applies those controls **"in the past"**, at the time they actually happened given your ping.
3. The server sends back an **"authority state"** (the real position).
4. When that reaches the client it is outdated, so the client **re-applies every control input since that time** on top of the authoritative state. This is client-side prediction with server reconciliation and input replay.
5. **Other players are shown in *extrapolated* time.** In Anton's words, the client knows their old position, speed and controls and *predicts the future position*. This is the key point for hit registration. It is not the CS/Battlefield model of interpolating other players in the past.
6. Anton explicitly rejects the CS/Battlefield interpolation-plus-lag-compensation model, because it "puts anyone with a greater ping in a better position". He also rejects the Q3 no-interpolation model and the MMO thin-client model ("sluggish" controls).
7. **"The server broadcast positions, not controls, so no one depends on the slowest client."** Better ping gives better awareness and aim. Your own vehicle's control is *not* ping-dependent, only packet-loss dependent.
8. On stability: "a stable 100 msec is sometimes better than 'average' 50 msec if it is actually 10..110 ms". Jitter hurts more than latency.
9. On packet loss: controls are sent with redundancy. If **all controls are lost in a ~700 ms window**, they are too old to re-apply. 3–5 % loss "should be ok".
10. **The in-game packet-loss stat counts only *reliable* traffic.** Loss on unreliable traffic cannot be measured by the game, so the displayed PL **understates the real loss**. *Important: our packet captures must measure loss independently.*
11. Shooting is described as a "cool" interaction for netcode, because results are mostly binary (miss/ricochet vs damage). Small desync shows up as tiny teleports.

### 1.2 "Fair Play F.A.Q and Game Mechanic Changes", 10 Dec 2016 [OFFICIAL]
<https://warthunder.com/en/news/4393-development-fair-play-f-a-q-and-game-mechanic-changes-en>

- **"All decisions, physics and hits are calculated on the server side."** The client cannot turn a miss into a hit.
- **Client-side replays** are accurate only near the local player. Distant objects and objects out of view are sent "with heavy compression (or not at all)". This is **interest management / relevancy-based update rates**. *[INFERENCE: update rates for a target probably depend on distance and view direction. That has to be tested.]*
- **Server replays** record position and orientation at **"~10–15 times per second"** on average. *[INFERENCE: this is probably where the "WT is 10 tick" myth comes from. People measured the replay sample rate, not the simulation rate.]*
- **Hit effects (sparks/explosions) for rapid-fire weapons are drawn on the client regardless of the server.** If they waited for the server, the feedback would arrive after the target is gone. Gaijin itself says that with 100–120 ms ping and small packet loss, that lag "can take up to half a second".
- **The server-confirmed hit indicator is the lines drawn around the gunsight** ("registers up to 8 hits"). "An attentive player can notice the lag between the shots and the server messages." *→ This gives us a **directly measurable server round-trip signal** (§ Experiment B).*
- **Aim-cursor positions are sent to the server "several times per second (more than ten)".** Replays of the cursor look "robotic and twitchy" because of this.
- Kill-cam shell paths are drawn straight from the firing point to the impact point, not along the real ballistic path. Do not use the kill cam as evidence.
- HE fragments that don't damage modules are neither simulated on the client nor drawn.
- Detection/visibility values (2016, patch 1.65): the unconditional detection radius was roughly 360 m and was cut about 5×. Third-person view detection went from 2 km to 1200 m. Marker distance went from 1200 to 900 m. Binocular multiplier went from 2.6 to 1.4, sight multiplier from 2.4 to 2. Tanks are transmitted "a little earlier than the player can see them". (This matters for "tanks popping in".)

### 1.3 "Shell and bullet synchronization", 6 Oct 2017 [OFFICIAL]
<https://warthunder.com/en/news/5005-development-shell-and-bullet-synchronization-en>

- Shell trajectories start **at the same time on server and client with the same physical model**. From this patch they are **synchronized "using the same time sampling rate"**, so trajectories match "in 99 % of cases", and **client trajectory no longer depends on FPS**. *[INFERENCE: there is a fixed ballistic timestep shared by client and server. Its value was not published.]*
- "Situations where you see a registered hit in your client but it doesn't count on the server are reduced to the absolute minimum possible **in our net sync model**." Unstable ping and packet loss can still cause problems, because the server has to know a shot was fired, and high ping makes the client's view less current.
- Every single projectile is simulated, whatever the fire rate or caliber. "Many hundreds of thousands of bullets" can be in flight.
- An admin comment says tanks benefit too, "may help with AAA vs planes".

### 1.4 "Are 'sparks' gone? About WT netcode", Anton Yudintsev on Reddit, ~Oct 2017 [OFFICIAL] ★ key source
Full text: `research/raw/anton_reddit_2017.md`. Original: <https://www.reddit.com/r/Warthunder/comments/74sm7k/are_sparks_gone_about_wt_netcode/>

**What it settles:**
1. **"Net code in WT is extrapolation base. So, when you see enemy – it is extrapolated."** Enemies are shown in *predicted future* time from velocity, acceleration and so on. **No interpolation and no shot rewind (lag compensation) for hit checks.** Anton explicitly rejects CS/BF-style rewinding because it "favors BIGGER ping" (the 1000 ms door-peeker example).
2. **"Tickrate is 48Hz"**, stated for the **bullet time-sampling rate**. Client and server step every projectile at the same fixed 48 Hz (20.83 ms), and shots are fired on that tick grid. On your PC the bullet is **linearly interpolated between 48 Hz positions** for rendering ("if you have 100 fps, each second frame bullet is in an average position"). Anton separately mentions a **"logical tick rate"**. He does not give its value.
   **[MEASURED] 2026:** ground vehicles (tank MG) fire on a **24 Hz** step (41.67 ms), the same at 60 and 120 FPS, with server→client packets at ≈ 24.3 Hz. In planes the packets run at **≈ 48–49 Hz** and the own-shot sound shows no tick wait. So 48 Hz fits air; ground runs at half of it.
3. The server **rewinds and re-applies *controls*** (yours and everyone's) and sends the corrected positions to all clients. That is input rewind for movement, not for shots.
4. **Hit signals, precisely defined:**
   - **Small spark = client-side hit only.** It may be a false positive.
   - **"Hit" (animated cross) = server-side hit.** "If there is no 'Hit' (animated cross) – there was no server-side hit."
   - **Big sparks (30 mm+) are server-replicated** (since ~mid-2017). You see them only for a registered server hit.
5. **A false positive happens when the target used unexpected controls while your burst was in flight**, and the information didn't reach you in time because of *his or your* ping. Anton's worked example: **target at 10 ms ping, shooter at 70 ms → "99 % accuracy"**. If the target has 70–100 ms, his dodges may never show on your screen (left-then-right looks like "didn't move at all"). **⇒ The model predicts that the *target's* latency matters as much as the shooter's.** That is directly testable (Exp. G).
6. The model "favors lower ping", and Anton calls the remaining false positives the price of respecting the enemy's "awesomeness" (his controls).
7. **A considered improvement (not confirmed as ever shipped):** "limited interpolation and then extrapolation" for aircraft. Stable ping under X (~50 ms) would give 100 % accurate shots, with extrapolation beyond that. Anton raised problems with environment interaction (water waves, naval). *[Open: did this ship? Exp. C/G can detect it. With interpolation, B's view of A **lags** by a constant amount. With extrapolation, it **overshoots** on reversals.]*
8. **Clock warning:** "20 % of PC players have internally broken CPU HW clock". The precise timer is disabled or inaccurate, so the fallback runs at **~10 ms precision**. *→ We must check that our own PCs' high-resolution timers are healthy before timing anything (PLAN §2.3).*
9. The devblog link he gave (`devblog/current/898`) now redirects to an unrelated 2014 article. The intended article is the collision explainer (§1.1, news/4116).

### 1.5 Things Gaijin has never published [OFFICIAL – absence]
- Whether the **"logical"/physics server tick** equals the 48 Hz ballistic sampling rate. **[MEASURED]:** not for ground vehicles (24 Hz); plausibly yes for air (48 Hz packets).
- The server→client snapshot send rate, and whether it varies per object. **[MEASURED]:** ≈ 24.3 Hz in ground battles, ≈ 49 Hz in air; per-object variation not tested yet.
- ~~Whether the server uses lag compensation for hits~~ → **answered: no, extrapolation model (§1.4)**.
- ~~The ballistic integration timestep~~ → **answered: 48 Hz (§1.4)**.
- Whether the "interpolation under X ms" hybrid for aircraft (§1.4 point 7) was ever implemented.
- A 2026 forum thread asking for the current tick rate (<https://forum.warthunder.com/t/can-we-get-an-update-to-what-the-actual-server-tick-rate-is/329851>) has no developer answer. Third-party ping sites say the same: "Gaijin has never published it" (<https://pingpackettest.com/game/war-thunder>).

---

## 2. Community claims [COMMUNITY]

| Claim | Source | Notes |
|---|---|---|
| **48 Hz** tick rate | Anton 2017 Reddit post | Official (§1.4), stated for the bullet time-sampling rate. **[MEASURED]:** fits air (48 Hz packets); ground shots run on 24 Hz. |
| **10 tick rate** servers | <https://www.reddit.com/r/Warthunder/comments/1g7kgi5/friendly_reminder_this_game_runs_on_10_tic_rate/> (`research/raw/reddit_10_tick_thread.md`) | The post is a "Drama"-flaired rant with **no method or data**. It contradicts the official 48 Hz. The 10–15 Hz server-replay sample rate (§1.2) is the likely source of the confusion. **[MEASURED]: 10 Hz ruled out** on the shot path, ground and air. |
| "Feels very not 40 anymore": turret snapping, tanks sliding at range, spectators not seeing stabilizers | WT forum, Jun 2026 (link above) | Fits distance-based update-rate reduction (§1.2). |
| 30 Hz / "around 40 Hz" | pingpackettest.com | Explicitly "estimated", no source. Ignore. |
| Enlisted runs at **15 Hz** | <https://community.gaijin.net/issues/p/enlisted/i/Y4UNm2kHcoHY> | Matches the Dagor `PHYS_DEFAULT_BOT_TICKRATE = 15` (§3). Possibly a bot or low-frequency entity rate. |
| Shells "vanish", bombs land far from the predicted spot, hits deal damage at the wrong point, at 12–32 ms ping and 0 % PL | <https://forum.warthunder.com/t/netcode-of-the-game-beyond-repair-full-rework-needed-asap/27880> | No staff reply. |
| Shots don't register when the enemy fires ~0.5 s after you (EU, 20–25 ms, 0 PL) | <https://forum.warthunder.com/t/server-desync-with-shots/119646> | Fits the server resolving the higher-latency or earlier-processed kill first ("ghost shells"). |
| "Massive delay with 0 % PL and usual ping"; ghost shell when the server processes the other player's kill first | <https://forum.warthunder.com/t/does-high-ping-help-you/204034> | Fits Anton's point that the displayed PL understates real loss. |
| "Sparks are client-side" | Steam discussions | **Confirmed officially** in §1.2. |
| Jets: radar locks and missiles "heavily ping-dependent", gun hits at jet speed are "luck" | WT forum thread 27880 | This is the user's own hypothesis. Experiment C tests it. |
| Large desync reported in 2025 (shell visibly hits, registers as a miss) | <https://community.gaijin.net/issues/p/warthunder/i/xlpk7N3wROvv> | Bug-tracker entry. |
| Long sessions: playback desync after ~15–45 min of replay | WT forum 2026 | Replays drift. Keep test replays short. |

---

## 3. Gaijin's open-source Dagor Engine: what the code shows [SOURCE CODE]

Gaijin publishes **DagorEngine** at <https://github.com/GaijinEntertainment/DagorEngine> (last push 2026-11-07). It contains `prog/daNetGame/`, the networked-game framework used by **Enlisted and newer Gaijin titles**. **War Thunder's own game code (the "aces" codebase) is NOT public.** So these numbers show Gaijin's *house style and engine defaults*. They are **not proof of WT's values**. WT's netcode also predates daNetGame, and Anton describes WT as *extrapolating*, while daNetGame *interpolates and lag-compensates*.

Copies of the relevant files are in `reference/dagor_engine_netcode_src/`.

### 3.1 Transport
- **ENet** (UDP, with reliable/unreliable/sequenced channels): `prog/3rdPartyLibs/enet/` with a Gaijin `enet_dagor.h` wrapper. *[INFERENCE: WT very likely also uses UDP via ENet or a predecessor. Expect UDP game traffic in captures.]*

### 3.2 Tick-rate constants (`prog/daNetGame/phys/physConsts.h`)
```
PHYS_DEFAULT_TICKRATE                    30     // players
PHYS_DEFAULT_BOT_TICKRATE                15     // bots / low-frequency entities
PHYS_MIN_TICKRATE                        8
PHYS_MAX_TICKRATE                        128    // configurable via settings "tickrate"/"bottickrate"
PHYS_MIN_INTERP_DELAY_TICKS              2
PHYS_MAX_INTERP_DELAY_TICKS              4      // "too much interpolation might cause excessive 'shot around a corner'"
PHYS_CONTROLS_NET_REDUNDANCY             2      // controls duplicated -> effectively 2x tickrate on the wire
PHYS_MAX_CONTROLS_TICKS_DELTA_SEC        0.375  // "2x of this gives maximum playable ping" (~750 ms)
PHYS_SEND_AUTH_STATE_PERIOD_SEC          1.0    // full authoritative state every 1 s (reliable)
PHYS_MAX_INTERP_FROM_TIMESPEED_DELAY_SEC 1.5
```
- Tick rate can be changed at runtime (`phys_set_tickrate`, `EventTickrateChanged`).
- **Two classes of entity: Normal (30 Hz) and LowFreq (15 Hz).** Snapshots carry a `LOW_FREQ_TICKRATE` flag.
- `netPhys.cpp`: `ControlsMsg` is `UNRELIABLE_SEQUENCED` with a comment saying it is duplicated for time redundancy. `AAStateMsg` (full authority-approved state) is reliable-unordered. `AAPartialStateMsg` is unreliable.
- `PHYS_MAX_LAGGED_PHYS_TIME = 0.35 s`. Default `net.cl_max_extrapolation_time = 0.6 s`.

### 3.3 Lag compensation (`phys/lagCompensation*.{h,inl}`)
- The server keeps a history of quantized positions and rewinds to the shooter's view time. Errors include `TimeGapIsTooBig // Perhaps server lagged`.
- `MAX_UNLAG_TIME_SEC = 1.5 + maxTimeStep*4 + 0.25` ≈ **2.0 s** at a 15 Hz low-frequency rate.
- Interpolation delay is 2–4 ticks, which is **67–133 ms at 30 Hz**.

### 3.4 What this means for WT [INFERENCE]
- Gaijin's modern default (daNetGame) is **30 Hz** sim/net for players. **WT officially uses 48 Hz** for ballistics (§1.4), an older, flight-focused codebase with a different (extrapolation) model. **[MEASURED]:** air ≈ 48 Hz, ground 24 Hz. **10 Hz as a simulation rate is ruled out.** 10–15 Hz is the **server-replay sample rate** (official) and possibly the **update rate for distant or low-priority objects**. The open question is no longer "is it 10 Hz" but **how much prediction error extrapolation adds during manoeuvres, at real ping and update rates**.
- At jet speeds, every tick or update interval matters:

| Target speed | m per 1/10 s | m per 1/15 s | m per 1/30 s | m per 1/48 s | m per 1/60 s |
|---|---|---|---|---|---|
| 500 km/h (139 m/s) | 13.9 | 9.3 | 4.6 | 2.9 | 2.3 |
| 1000 km/h (278 m/s) | 27.8 | 18.5 | 9.3 | 5.8 | 4.6 |
| 2000 km/h closure (556 m/s) | 55.6 | 37.0 | 18.5 | 11.6 | 9.3 |

A fighter's wingspan is about 10–15 m. With extrapolation, the **position error during a hard manoeuvre** grows with update interval plus latency squared (it depends on acceleration: ½·a·t²). At 9 g (88 m/s²), 100 ms of blind extrapolation gives ½·88·0.1² ≈ **0.44 m**. 250 ms gives **2.75 m**. 500 ms gives **11 m**, a whole aircraft. **So extrapolation error under manoeuvre is the most likely main cause of air hit-reg complaints, more than tick rate alone.** The experiment has to separate these factors.

---

## 4. Useful local tools Gaijin provides [OFFICIAL / well known]

- **Localhost telemetry API** on `http://127.0.0.1:8111` while the game runs: `/state`, `/indicators` (own vehicle: IAS/TAS, altitude, g, AoA, throttle…), `/map_obj.json` (positions of map objects in normalized map coordinates, including enemies shown on the minimap), `/map_info.json`, `/hudmsg?lastEvt=0&lastDmg=0` (kill/damage feed), `/gamechat`, `/mission.json`. It is read-only, officially exposed and used by many community tools. **We poll it at high frequency with precise timestamps.**
- **Client replays** (`.wrpl`, in `<WT>/Replays`) and **server replays** (downloadable from the battle log on warthunder.com). Server replays are the ground truth for hit adjudication.
- **Custom battles / Test Flight / user missions.** Custom battles give a controlled, private two-player setup. Hosting usually needs a premium account; anyone can join.
- **In-game network stats overlay** (ping / PL / FPS; enable in Options → Main → "Show network indicators" or similar). Remember the PL caveat (§1.1 point 10).

## 5. Rules for the experiment

- **Never** inject into, read memory from, or modify the game client. War Thunder uses Easy Anti-Cheat. Passive packet capture (Npcap/Wireshark) and the official 8111 API are non-invasive.
- **Never** use latency/loss injection (e.g. clumsy, NetLimiter) in matchmade battles. That is lag-switching and bannable, and Gaijin has added "protection against network manipulation". If we use it at all, only in a private custom battle between your own two accounts, at your own risk.
- Do not decrypt traffic. We only use timing, size and direction metadata.
