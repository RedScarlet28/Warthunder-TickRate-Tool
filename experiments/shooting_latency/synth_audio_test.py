#!/usr/bin/env python3
"""
End-to-end validation of the AUDIO method with real WAV files.

Simulates: press on the shooter PC (clock offset vs Salty) -> client fire grid -> uplink jitter
-> server tick -> downlink jitter -> observer game frame (137 fps, drifting) -> 10 ms audio mixing
block -> output latency -> loopback recording on a sound card whose clock is 35 ppm off, with
OS buffer-arrival jitter in the timing log. Gunshots are decaying noise bursts on top of engine
rumble and noise.

Then runs audio_onsets.py (clock fit + onset detection) and analyze_shooting.py (audio mode),
and checks onset timing accuracy and the recovered tick period.

    python synth_audio_test.py
"""
import csv, json, os, subprocess, sys, tempfile, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RATE = 48000
SCEN = {  # name: (client_grid_hz, server_hz, same_phase, expected_remote_T, expected_local_T)
    "A1_48Hz_global_grid": (48, 48, True, 1000 / 48, 1000 / 48),
    "A2_10Hz_server":      (0, 10, False, 100.0, None),
    "A3_48Hz_indep_grids": (48, 48, False, 1000 / 48, 1000 / 48),
}


def next_grid(t, hz, ph):
    return t if not hz else ph + np.ceil((t - ph) * hz) / hz


def write_recording(path, t_start_wall, dur, shot_walls, rng, drift_ppm=35.0):
    """Create a loopback WAV + timing.jsonl. shot_walls are wall times (this PC's clock) when the sound
    leaves the game's mixer; output latency is added here."""
    rate_true = RATE * (1 + drift_ppm * 1e-6)
    n = int(dur * RATE)
    t = np.arange(n) / RATE
    x = 0.15 * np.sin(2 * np.pi * 80 * t) + 0.05 * np.sin(2 * np.pi * 163 * t + 1) + rng.normal(0, 0.004, n)
    burst_len = int(0.06 * RATE)
    env = np.exp(-np.arange(burst_len) / (0.012 * RATE))
    true_onset_samples = []
    for sw in shot_walls:
        # mixer starts sounds on 480-sample block boundaries of the SOUND-CARD clock, then +20 ms output latency
        k = int(np.ceil((sw - t_start_wall) * rate_true / 480) * 480) + int(0.020 * RATE)
        if 0 <= k < n - burst_len:
            x[k:k + burst_len] += 0.5 * rng.normal(0, 1, burst_len) * env
            true_onset_samples.append(k)
    x = np.clip(x, -1, 1)
    with wave.open(path + ".wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    with open(path + ".timing.jsonl", "w") as f:
        f.write(json.dumps({"ep": "_meta", "rate": RATE}) + "\n")
        for se in range(256, n, 256):
            arr = t_start_wall + se / rate_true + 0.003 + rng.exponential(0.0005) + (rng.random() < 0.02) * rng.uniform(0, 0.008)
            f.write(json.dumps({"sample_end": se, "t_wall_ns": int(arr * 1e9)}) + "\n")
    return np.array(true_onset_samples), rate_true


def run(name, chz, shz, same, expT, expL, rng):
    out = tempfile.mkdtemp(prefix=name + "_")
    off = 0.003217
    n = 250
    t0 = 1_794_700_000.0 + rng.uniform(0, 1)
    press = t0 + 2 + np.cumsum(rng.uniform(0.6, 2.0, n))
    end = press[-1] + 2
    ph_s = rng.uniform(0, 1); ph_c = ph_s if same else rng.uniform(0, 1)
    with open(os.path.join(out, "inputs.jsonl"), "w") as f:
        for p in press:
            f.write(json.dumps({"t_wall_ns": int((p - off) * 1e9), "btn": "mouse_left", "down": True, "injected": False}) + "\n")
            f.write(json.dumps({"t_wall_ns": int((p - off + 0.12) * 1e9), "btn": "mouse_left", "down": False, "injected": False}) + "\n")
    with open(os.path.join(out, "clock.jsonl"), "w") as f:
        for tl in np.arange(t0 - off, end, 0.05):
            f.write(json.dumps({"t_local_ns": int(tl * 1e9), "offset_ns": int((off + rng.normal(0, 3e-5)) * 1e9),
                                "delay_ns": int((0.00025 + abs(rng.normal(0, 1e-4))) * 1e9)}) + "\n")
    fire = next_grid(press + 0.002, chz, ph_c)
    send = next_grid(fire + rng.normal(0.014, 0.0015, n), shz, ph_s)
    arr_obs = send + rng.normal(0.012, 0.0015, n)
    gph = rng.uniform(0, 1, 2); gfps = 137 * (1 + 60e-6)
    obs_sound = next_grid(arr_obs, gfps, gph[0])             # observer = Salty clock (mixer block added in write_recording)
    sh_sound_local = next_grid(fire - off, gfps, gph[1])    # shooter local clock

    tr_o, rt_o = write_recording(os.path.join(out, "obs"), t0, end - t0, obs_sound, rng)
    tr_s, rt_s = write_recording(os.path.join(out, "sh"), t0 - off, end - t0, sh_sound_local, rng, drift_ppm=-22.0)

    py = [sys.executable, "-I"]
    for tag in ("obs", "sh"):
        r = subprocess.run(py + [os.path.join(HERE, "audio_onsets.py"), os.path.join(out, tag + ".wav")],
                           capture_output=True, text=True)
        if r.returncode:
            print(name, "audio_onsets FAILED", r.stderr[-1500:]); return False
    # onset accuracy vs truth (observer)
    det = np.array([float(rw["t_wall_s"]) for rw in csv.DictReader(open(os.path.join(out, "obs.onsets.csv")))])
    truth = t0 + tr_o / rt_o
    err = np.array([det[np.argmin(np.abs(det - tt))] - tt for tt in truth]) * 1000
    r = subprocess.run(py + [os.path.join(HERE, "analyze_shooting.py"),
                             "--shooter-inputs", os.path.join(out, "inputs.jsonl"), "--shooter-clock", os.path.join(out, "clock.jsonl"),
                             "--observer-wall-onsets", os.path.join(out, "obs.onsets.csv"),
                             "--shooter-wall-onsets", os.path.join(out, "sh.onsets.csv"),
                             "--observer-game-fps", "137", "--shooter-game-fps", "137",
                             "--boot", "15", "--out", os.path.join(out, "analysis")], capture_output=True, text=True)
    if r.returncode:
        print(name, "analyzer FAILED", r.stderr[-2500:]); return False
    s = json.load(open(os.path.join(out, "analysis", "summary.json")))
    v = s["verdict"]
    ok = v.get("period_ms") is not None and abs(v["period_ms"] - expT) <= max(2.0, 0.05 * expT)
    line = (f"{name:22s} truth {expT:6.1f} ms | VERDICT {v.get('period_ms')} ms [{v['status'].split(':')[0]}] "
            f"| fit {s['remote_fit'].get('T_ms')} | detected {len(det)}/{len(truth)} shots, onset error "
            f"median {np.median(err):+.3f} ms, p95 |err| {np.percentile(np.abs(err), 95):.3f} ms, mixer {s['observer_video_sync'].get('mixer_block_ms')} ms")
    if expL:
        lv = s.get("local_sound_verdict", {})
        okl = lv.get("period_ms") is not None and abs(lv["period_ms"] - expL) <= 2.0
        ok = ok and okl
        line += f" | shooter own-shot {lv.get('period_ms')} ms"
    print(("PASS " if ok else "FAIL ") + line)
    return ok


def main():
    rng = np.random.default_rng(7)
    res = [run(k, *v, rng) for k, v in SCEN.items()]
    print("\nALL PASS" if all(res) else "\nSOME FAILED")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
