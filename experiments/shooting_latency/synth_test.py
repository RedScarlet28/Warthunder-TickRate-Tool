#!/usr/bin/env python3
"""
Validate analyze_shooting.py on simulated sessions with KNOWN tick rates.

Simulates the full chain:
  press (shooter clock, offset vs Salty) -> optional client fire grid -> uplink jitter
  -> server tick -> downlink jitter -> observer monitor refresh -> OBS capture at its fps
  + the sync-flash overlay on every recording + a clock_sync log for the shooter PC.
Writes the same file formats the real tools produce, runs the analyzer and checks the
recovered tick period against the truth.

    python synth_test.py            # all scenarios
    python synth_test.py --quick    # fewer bootstraps
"""
import argparse, csv, datetime as dt, json, os, subprocess, sys, tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

SCENARIOS = {
    # name: (client_fire_grid_hz or 0, server_tick_hz, same_phase_grid, expected_T_ms, expected_local_T_ms)
    "S1_48Hz_global_grid":      (48, 48, True, 1000 / 48, 1000 / 48),
    "S2_10Hz_server_no_grid":   (0, 10, False, 100.0, None),
    "S3_48Hz_client+server_indep": (48, 48, False, 1000 / 48, 1000 / 48),
    "S4_30Hz_server_no_grid":   (0, 30, False, 1000 / 30, None),
}


def next_grid(t, hz, phase):
    if not hz:
        return t
    P = 1.0 / hz
    return phase + np.ceil((t - phase) / P) * P


def simulate(out, client_hz, server_hz, same_phase, rng, n=300, obs_fps=127.0, mon_hz=137.0 * (1 + 60e-6),
             sh_offset=0.003217):
    t0 = 1_794_600_000.0 + rng.uniform(0, 1)
    gaps = rng.uniform(0.6, 2.0, n)
    press_ref = t0 + 3 + np.cumsum(gaps)
    end = press_ref[-1] + 3
    ph_s = rng.uniform(0, 1)
    ph_c = ph_s if same_phase else rng.uniform(0, 1)

    # --- shooter input log (shooter LOCAL clock = ref - offset)
    with open(os.path.join(out, "inputs.jsonl"), "w") as f:
        f.write(json.dumps({"ep": "_meta"}) + "\n")
        for p in press_ref:
            loc = p - sh_offset
            f.write(json.dumps({"t_wall_ns": int(loc * 1e9), "btn": "mouse_left", "down": True, "injected": False}) + "\n")
            f.write(json.dumps({"t_wall_ns": int((loc + 0.15) * 1e9), "btn": "mouse_left", "down": False, "injected": False}) + "\n")
    # --- shooter clock log vs Salty
    with open(os.path.join(out, "clock.jsonl"), "w") as f:
        f.write(json.dumps({"ep": "_meta"}) + "\n")
        for tl in np.arange(t0 - sh_offset, end, 0.05):
            dly = 0.00025 + abs(rng.normal(0, 0.0001))
            f.write(json.dumps({"t_local_ns": int(tl * 1e9), "offset_ns": int((sh_offset + rng.normal(0, 3e-5)) * 1e9),
                                "delay_ns": int(dly * 1e9)}) + "\n")

    # --- chain
    fire = next_grid(press_ref + 0.002, client_hz, ph_c)            # input lag 2 ms, client fire grid
    arrive_srv = fire + rng.normal(0.014, 0.0015, n)
    send = next_grid(arrive_srv, server_hz, ph_s)
    arrive_obs = send + rng.normal(0.012, 0.0015, n)

    def displayed(t, hz, phase):  # next monitor refresh + 1 frame pipeline
        return next_grid(t, hz, phase) + 1.0 / hz

    def captured(t, fps, v0):      # first capture frame at/after t -> (frame, video time)
        fr = np.ceil((t - v0) * fps).astype(int)
        return fr, fr / fps

    mon_ph_o, mon_ph_s = rng.uniform(0, 1, 2)
    v0_o = t0 + 0.37; v0_s = t0 - sh_offset + 0.81                  # recording start (observer ref clock / shooter local clock)
    rem_fr, rem_t = captured(displayed(arrive_obs, mon_hz, mon_ph_o), obs_fps, v0_o)

    def flashes(v0, start, stop, mon_ph):
        secs = np.arange(np.ceil(start), stop)
        return captured(displayed(secs, mon_hz, mon_ph), obs_fps, v0)

    fl_fr, fl_t = flashes(v0_o, v0_o, end, mon_ph_o)
    with open(os.path.join(out, "observer_events.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["roi", "frame", "t_s", "z"])
        rows = [("flash", a, b) for a, b in zip(fl_fr, fl_t)] + [("enemy_fire", a, b) for a, b in zip(rem_fr, rem_t)]
        for r, a, b in sorted(rows, key=lambda x: x[1]):
            w.writerow([r, a, f"{b:.6f}", 50])

    # shooter's own video, in its LOCAL clock
    fire_local = fire - sh_offset
    mz_fr, mz_t = captured(displayed(fire_local, mon_hz, mon_ph_s), obs_fps, v0_s)
    sfl_fr, sfl_t = flashes(v0_s, v0_s, end - sh_offset, mon_ph_s)
    with open(os.path.join(out, "shooter_events.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["roi", "frame", "t_s", "z"])
        rows = [("flash", a, b) for a, b in zip(sfl_fr, sfl_t)] + [("muzzle", a, b) for a, b in zip(mz_fr, mz_t)]
        for r, a, b in sorted(rows, key=lambda x: x[1]):
            w.writerow([r, a, f"{b:.6f}", 50])

    iso = lambda s: dt.datetime.fromtimestamp(np.floor(s)).isoformat(sep=" ")
    return iso(v0_o), iso(v0_s), obs_fps, 137.0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    rng = np.random.default_rng(42)
    results = []
    for name, (chz, shz, same, expT, expL) in SCENARIOS.items():
        out = tempfile.mkdtemp(prefix=name + "_")
        ostart, sstart, fps, gfps = simulate(out, chz, shz, same, rng)
        cmd = [sys.executable, "-I", os.path.join(HERE, "analyze_shooting.py"),
               "--shooter-inputs", os.path.join(out, "inputs.jsonl"), "--shooter-clock", os.path.join(out, "clock.jsonl"),
               "--observer-events", os.path.join(out, "observer_events.csv"), "--observer-start", ostart,
               "--observer-fps", str(fps), "--shooter-events", os.path.join(out, "shooter_events.csv"),
               "--shooter-start", sstart, "--shooter-fps", str(fps), "--boot", "15" if a.quick else "60",
               "--observer-game-fps", str(gfps), "--shooter-game-fps", str(gfps),
               "--out", os.path.join(out, "analysis")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(name, "FAILED\n", r.stderr[-2000:]); results.append((name, False)); continue
        s = json.load(open(os.path.join(out, "analysis", "summary.json")))
        rf = s["remote_fit"]; v = s["verdict"]
        ok = v.get("period_ms") is not None and abs(v["period_ms"] - expT) <= max(2.0, 0.05 * expT)
        line = (f"{name:30s} truth {expT:6.1f} ms | VERDICT {v.get('period_ms')} ms [{v['status'].split(':')[0]}]"
                f" | fit {rf['T_ms']} ms K={rf['best_K']} CI={rf['T_ms_CI95']}")
        if expL:
            lf = s.get("local_muzzle_verdict", {})
            okl = lf.get("period_ms") is not None and abs(lf["period_ms"] - expL) <= 2.0
            ok = ok and okl
            line += f" | shooter muzzle {lf.get('period_ms')} ms"
        top = s["remote_onset_rayleigh_peaks_hz"][0]
        line += f" | top fold peak {top['hz']} Hz{' (frame artifact)' if top['frame_artifact'] else ''}"
        print(("PASS " if ok else "FAIL ") + line)
        print("      sync:", s["observer_video_sync"], " clock:", s["shooter_clock"]["offset_ms_median"], "ms (truth 3.217)")
        results.append((name, ok))
    print("\nALL PASS" if all(ok for _, ok in results) else "\nSOME FAILED")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
