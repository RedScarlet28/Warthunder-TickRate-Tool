#!/usr/bin/env python3
"""
Detect gunshot onsets in a loopback recording and give them precise wall-clock times.

1. Clock: fits wall_time = a * sample_index + b from the .timing.jsonl written by
   audio_recorder.py. Buffers can only arrive LATE (OS scheduling), never early, so the fit
   uses the LOWER ENVELOPE (iterative fit keeping points at/below the line). That removes jitter
   and the sound card's clock drift.
2. Onsets: high-pass filter (gunshots are broadband transients, engine rumble is low frequency),
   1 ms energy envelope, adaptive threshold (k x rolling noise floor), refractory period.
   Onset time = the first sample where energy crosses the threshold, refined back to where the
   rise starts.

Output CSV: roi,t_wall_s,sample,strength   (roi = "sound"), for analyze_shooting.py
  --observer-wall-onsets / --shooter-wall-onsets.

Usage:
  python audio_onsets.py audio_X.wav --out onsets.csv [--hp 1500] [--k 8] [--refractory-ms 25]
  python audio_onsets.py audio_X.wav --plot       # writes a PNG to check detection by eye
NOTE: War Thunder may delay sound with distance (speed of sound, ~2.9 ms per metre).
Keep the shooter at a FIXED distance from the observer during a run. A constant offset does not
affect the tick-period estimate.
"""
import argparse, csv, json, os, sys, wave

import numpy as np


def load_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        sys.exit("expected 16-bit PCM")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32).reshape(-1, ch) / 32768.0
    return x.mean(axis=1), rate


def clock_fit(timing_path, rate):
    s, t = [], []
    with open(timing_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "sample_end" in r:
                s.append(r["sample_end"]); t.append(r["t_wall_ns"] / 1e9)
    s, t = np.array(s, float), np.array(t)
    if len(s) < 50:
        sys.exit("timing file too short")
    t0 = t[0]; tt = t - t0
    # Mapping sample index -> wall time. Buffers can only arrive LATE, so every fit is a LOWER ENVELOPE.
    # Two things break a single straight line:
    #  * delivery gaps: some drivers (e.g. HyperX virtual surround) send NOTHING while the output is
    #    silent, so time jumps ahead while the sample count stands still;
    #  * small steps: WASAPI loopback occasionally skips/repeats a few ms of samples to absorb the rate
    #    difference between sound card and system clock.
    # So: split at gaps and at envelope steps, use ONE common rate (the card's crystal is stable),
    # and give every segment its own offset.
    def lower_fit(ss, ts, slope=None):
        if slope is None:
            sa, sb = np.polyfit(ss, ts, 1)
            for _ in range(30):
                rr = ts - (sa * ss + sb); m = rr <= np.percentile(rr, 10)
                if m.sum() < 3: break
                sa, sb = np.polyfit(ss[m], ts[m], 1)
            return sa, sb
        rr = ts - slope * ss
        return slope, float(np.percentile(rr, 1) if len(rr) >= 200 else rr.min())

    buf = float(np.median(np.diff(s)))
    per = max(1, int(round(rate / buf)))                       # buffers per second
    gap_cuts = list(np.nonzero(np.diff(tt) > 0.040)[0] + 1)   # delivery gaps (normal spacing ~5 ms)

    def find_steps(a, pieces):
        cuts = []
        r = tt - a * s
        for c0, c1 in pieces:
            cuts.append(c0)
            n = c1 - c0
            if n < 6 * per:
                continue
            rp = r[c0:c1]; nck = n // per
            cm = np.array([rp[i * per:(i + 1) * per].min() for i in range(nck)])
            last = 0
            for i in range(1, nck - 1):
                left, right = np.median(cm[max(0, i - 3):i]), np.median(cm[i + 1:i + 4])
                if abs(right - left) > 0.0025:                        # > 2.5 ms step
                    lo, hi = (i - 1) * per, min(n, (i + 2) * per)
                    mid = (left + right) / 2; seg = rp[lo:hi]
                    if right < left:
                        k = lo + int(np.argmax(seg < mid))
                    else:
                        below = np.nonzero(seg < mid)[0]; k = lo + (int(below[-1]) + 1 if len(below) else 0)
                    if k - last > per:
                        cuts.append(c0 + k); last = k
        return sorted(set(cuts))

    def segments(cuts):
        c = list(cuts) + [len(s)]
        return [(c0, c1) for c0, c1 in zip(c[:-1], c[1:]) if c1 > c0]

    def common_rate(segs, fallback):
        sl, wt = [], []
        for c0, c1 in segs:
            if c1 - c0 >= 20 * per:
                sl.append(lower_fit(s[c0:c1], tt[c0:c1])[0]); wt.append(c1 - c0)
        return float(np.average(sl, weights=wt)) if sl else fallback

    # 1) common rate: median slope of lower-envelope fits on 10-s windows (a step inside a few windows
    #    cannot move the median)
    win = 10 * per; sl = []
    for i0 in range(0, len(s) - win, win // 2):
        i1 = i0 + win
        if np.any(np.diff(tt[i0:i1]) > 0.040):
            continue
        sl.append(lower_fit(s[i0:i1], tt[i0:i1])[0])
    a = float(np.median(sl)) if len(sl) >= 5 else lower_fit(s, tt)[0]
    # 2) cut at delivery gaps and at DOWN-steps (samples inserted); UP-steps (samples lost) are handled
    #    exactly by step 3, because the true offset only rises there
    cuts = [0] + gap_cuts
    downs = [c for c in find_steps(a, segments(cuts)) if c not in cuts]
    rr = tt - a * s
    downs = [c for c in downs if c > per and c < len(s) - per and
             np.min(rr[c:c + per]) < np.min(rr[c - per:c]) - 0.0025]
    segs = segments(sorted(set(cuts + downs)))
    # 3) per-buffer offset = max(min over the next W buffers, min over the previous W buffers),
    #    never crossing a segment cut. Exact for up-steps; jitter (always late) is removed by the min.
    W = max(5, per // 2)
    off = np.empty(len(s))
    from numpy.lib.stride_tricks import sliding_window_view as swv
    for c0, c1 in segs:
        x = rr[c0:c1]; n = len(x)
        if n <= W:
            off[c0:c1] = x.min(); continue
        pad_f = np.concatenate([x, np.full(W - 1, np.inf)]); fwd = swv(pad_f, W).min(axis=1)
        pad_b = np.concatenate([np.full(W - 1, np.inf), x]); bwd = swv(pad_b, W).min(axis=1)
        off[c0:c1] = np.maximum(fwd, bwd)
    resid = rr - off
    fits = [(0, a, 0)] * len(segs)          # kept for len() in info
    starts = None
    info = {"buffers": int(len(s)), "rate_nominal": rate, "rate_effective": round(1 / a, 3),
            "drift_ppm": round((1 / a / rate - 1) * 1e6, 2),
            "delivery_gaps": len(gap_cuts),
            "missing_time_s": round(float(tt[-1] - (s[-1] - s[0]) / rate), 2),
            "segments": len(segs), "down_steps": len(downs),
            "arrival_jitter_ms_p50": round(float(np.percentile(resid, 50)) * 1e3, 3),
            "arrival_jitter_ms_p99": round(float(np.percentile(resid, 99)) * 1e3, 3)}
    send = s.copy()

    def s2w(k):
        k = np.asarray(k, float)
        i = np.clip(np.searchsorted(send, k + 1, side="left"), 0, len(send) - 1)   # buffer holding sample k
        return t0 + a * k + off[i]
    # sample_end marks the END of a buffer: the arrival of sample k is ~ when sample k exists.
    return s2w, info


def highpass(x, rate, hz):
    try:
        from scipy.signal import butter, sosfiltfilt
        sos = butter(4, hz, "highpass", fs=rate, output="sos")
        return sosfiltfilt(sos, x)
    except ImportError:  # crude fallback: first difference
        return np.diff(x, prepend=x[0])


def detect(x, rate, hp, k, refractory_ms, floor_win_s=0.5):
    y = highpass(x, rate, hp)
    win = max(1, int(rate * 0.001))
    e = np.convolve(y * y, np.ones(win) / win, mode="same")
    # rolling noise floor (median over a long window, computed on a decimated copy)
    dec = max(1, int(rate * 0.005))
    ed = e[::dec]
    fw = max(3, int(floor_win_s * rate / dec))
    pad = np.pad(ed, (fw // 2, fw // 2), mode="edge")
    from numpy.lib.stride_tricks import sliding_window_view
    floor_d = np.median(sliding_window_view(pad, fw), axis=1)[: len(ed)]
    floor = np.repeat(floor_d, dec)[: len(e)] + 1e-12
    ratio = e / floor
    above = ratio > k
    onsets, strengths = [], []
    refr = int(refractory_ms / 1000 * rate)
    rearm_len = int(0.005 * rate)          # must stay quiet (ratio < rearm) this long before re-arming
    rearm_level = max(2.0, k / 4)
    quiet = ratio < rearm_level
    # quiet runs as (start, end) arrays (vectorized run-length encoding)
    qd = np.diff(np.concatenate([[0], quiet.astype(np.int8), [0]]))
    q_start, q_end = np.flatnonzero(qd == 1), np.flatnonzero(qd == -1)

    def quiet_between(a_, b_):
        """True if a quiet stretch of >= rearm_len samples lies within [a_, b_)."""
        i0 = np.searchsorted(q_end, a_ + rearm_len)          # runs ending late enough
        i1 = np.searchsorted(q_start, b_ - rearm_len, "right")  # runs starting early enough
        for r_ in range(i0, min(i1, len(q_start))):
            if min(q_end[r_], b_) - max(q_start[r_], a_) >= rearm_len:
                return True
        return False

    idx = np.flatnonzero(above)
    last = -10 ** 12
    armed = True
    prev_j = -10 ** 12
    for j in idx:
        if not armed and quiet_between(prev_j, j):
            armed = True       # sound died down since the last onset -> ready for the next shot
        if not armed or j - last < refr:
            continue
        # refine: walk back to where energy first rose above 2x floor
        st = j
        lim = max(0, j - int(0.005 * rate))
        while st > lim and ratio[st - 1] > 2:
            st -= 1
        onsets.append(st); strengths.append(float(ratio[j:j + win * 3].max()))
        last = j; prev_j = j; armed = False
    return np.array(onsets), np.array(strengths), y, ratio


def mixer_block(onset_samples, rate, lo=64, hi=4096):
    """The game's audio mixer starts sounds on block boundaries of the SOUND CARD clock, so onset sample
    indices are phase-locked to the block size. Find it with a sample-domain Rayleigh scan.
    Returns (block_samples, Z, block_ms) or None. Every DIVISOR of the true block locks equally well,
    while multiples of it do not, so take the LARGEST period whose Z is within 90 % of the best."""
    s = np.asarray(onset_samples, float)
    if len(s) < 40:
        return None
    periods = np.arange(lo, hi + 1)
    Z = np.empty(len(periods))
    for i in range(0, len(periods), 256):
        P = periods[i:i + 256, None]
        ph = 2 * np.pi * s[None, :] / P
        Z[i:i + 256] = (np.cos(ph).sum(1) ** 2 + np.sin(ph).sum(1) ** 2) / len(s)
    best = Z.max()
    if best < 15:
        return None
    cand = periods[Z >= 0.9 * best]
    P = int(cand.max())
    return P, float(Z[periods == P][0]), round(1000.0 * P / rate, 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("--timing", help="default: <wav without .wav>.timing.jsonl")
    ap.add_argument("--out", help="CSV output (default next to the wav)")
    ap.add_argument("--hp", type=float, default=1500)
    ap.add_argument("--k", type=float, default=8.0, help="onset threshold = k x noise floor")
    ap.add_argument("--refractory-ms", type=float, default=25)
    ap.add_argument("--burst-gap-ms", type=float, default=150,
                    help="keep only the FIRST onset of each burst: an onset needs this much silence (no onset) "
                         "before it. A machine-gun tap fires several rounds; only the first one is timed. 0 = keep all")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()
    timing = a.timing or a.wav[:-4] + ".timing.jsonl"
    out = a.out or a.wav[:-4] + ".onsets.csv"
    x, rate = load_wav(a.wav)
    s2w, info = clock_fit(timing, rate)
    on, strength, y, ratio = detect(x, rate, a.hp, a.k, a.refractory_ms)
    mb = mixer_block(on, rate)            # block detection uses ALL onsets (more statistics)
    info["onsets_all"] = int(len(on))
    if a.burst_gap_ms > 0 and len(on):
        keep = np.r_[True, np.diff(on) > a.burst_gap_ms / 1000 * rate]
        on, strength = on[keep], strength[keep]
    info["burst_gap_ms"] = a.burst_gap_ms
    tw = s2w(on)
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["roi", "t_wall_s", "sample", "strength"])
        for t, s, st in zip(tw, on, strength):
            w.writerow(["sound", f"{t:.6f}", int(s), f"{st:.1f}"])
    info["onsets"] = int(len(on))
    info["mixer_block"] = ({"samples": mb[0], "ms": mb[2], "Z": round(mb[1], 1)} if mb
                           else "not detected (too few onsets or no block locking)")
    with open(out[:-4] + ".meta.json", "w") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2)); print("->", out)
    if a.plot:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        # 20-s window in the busiest part of the recording (not the silent start)
        if len(on):
            cnt = np.searchsorted(on, on + rate * 20) - np.arange(len(on))
            s0 = max(0, int(on[int(np.argmax(cnt))]) - rate)
        else:
            s0 = 0
        s1 = min(len(x), s0 + rate * 20)
        tt = np.arange(s0, s1) / rate
        fig, ax = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
        ax[0].plot(tt, x[s0:s1], lw=.3); ax[0].set_title(f"raw, busiest 20 s ({s0 / rate:.0f}-{s1 / rate:.0f} s into the file); red = first round of each burst")
        ax[1].semilogy(tt, ratio[s0:s1] + 1e-3, lw=.3); ax[1].axhline(a.k, color="r")
        for o in on[(on >= s0) & (on < s1)]:
            ax[0].axvline(o / rate, color="r", lw=.5)
        ax[1].set_title("energy / noise floor (red line = threshold)"); ax[1].set_xlabel("s")
        fig.tight_layout(); fig.savefig(out[:-4] + ".png", dpi=110)


if __name__ == "__main__":
    main()
