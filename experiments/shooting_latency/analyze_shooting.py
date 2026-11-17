#!/usr/bin/env python3
"""
Shooting latency analyzer: from a fire-button press on the SHOOTER's PC to the shot
appearing on the OBSERVER's screen (and optionally on the shooter's own screen / hit marker).

All timestamps are converted to Salty's reference clock:
  * input log            (shooter wall clock)  -> + shooter clock offset
  * observer video time  -> wall clock via the sync-flash overlay (flash at every UTC second)
                         -> + observer clock offset
  (the PC that IS Salty's needs no clock log: its offset is 0)

Per press it finds the first matching visual onset, then estimates the tick period from the
SPREAD of the delays. The delay model is

    d = c + sum_{k=1..K} U(0, T) + U(0, F) + N(0, sigma)    K in {1, 2}, F = frame period (known)

which is fitted by maximum likelihood (FFT grid search), with a bootstrap CI for T.
It also runs a phase-folding (Rayleigh) scan of the onset times and flags peaks that are only
frame-rate artifacts (fps/k).

Inputs (from the other tools in this folder and ../../tools):
  --shooter-inputs   inputs_*.jsonl           (input_logger.py on the shooter PC)
  --observer-events  events.csv               (tools/video_event_timer.py on the observer's recording,
                                               ROIs: the flash square + where the shooter's muzzle/tracers appear)
  --observer-video   the recording file (its OBS file name gives the approximate start time), or
  --observer-start   "2026-11-14 19:03:12"     approximate local start time of that recording (±0.5 s)
  --observer-fps     recording fps (frame period F)
  --shooter-clock / --observer-clock   clock_*.jsonl from clock_sync.py (omit for Salty's PC)
Optional:
  --shooter-events + --shooter-video/--shooter-start + --shooter-fps + --local-rois muzzle,hit
  --pcap-shooter / --pcap-observer    packet captures (adds packet-level timing)

Run `python synth_test.py` to see a full example on simulated data.
"""
import argparse, csv, datetime as dt, json, os, re, sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

CANDIDATES_HZ = (10, 15, 16, 20, 24, 30, 48, 60, 64)


# ----------------------------------------------------------------------------- loading
def load_inputs(path, button, min_gap_ms):
    downs, ups = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            # injected events are ignored (macros/other tools), except the auto_fire.py log itself
            if r.get("btn") != button or (r.get("injected") and button != "autofire"):
                continue
            (downs if r["down"] else ups).append(r["t_wall_ns"] / 1e9)
    downs = np.array(sorted(downs))
    ups = np.array(sorted(ups))
    # isolated presses only: nothing pressed/held during the previous min_gap
    keep = []
    for i, t in enumerate(downs):
        prev_up = ups[ups < t]
        last_release = prev_up[-1] if len(prev_up) else -1e18
        prev_down = downs[i - 1] if i else -1e18
        if t - max(last_release, prev_down) >= min_gap_ms / 1000:
            keep.append(t)
    return downs, np.array(keep)


def load_clock(path):
    """Return a function local_wall_s -> offset_s (ref = local + offset), using min-RTT filtering."""
    if not path:
        return lambda t: np.zeros_like(np.asarray(t, float)), None
    t, off, dly = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "offset_ns" in r:
                t.append(r["t_local_ns"] / 1e9); off.append(r["offset_ns"] / 1e9); dly.append(r["delay_ns"] / 1e9)
    t, off, dly = map(np.array, (t, off, dly))
    if len(t) < 10:
        raise SystemExit(f"clock log {path} has too few samples")
    # per 5-s window keep the 20 % lowest-delay exchanges, take their median offset
    bins = np.floor((t - t[0]) / 5).astype(int)
    ct, co = [], []
    for b in np.unique(bins):
        m = bins == b
        thr = np.percentile(dly[m], 20)
        mm = m & (dly <= thr)
        ct.append(np.median(t[mm])); co.append(np.median(off[mm]))
    ct, co = np.array(ct), np.array(co)
    info = {"windows": int(len(ct)), "offset_ms_median": round(float(np.median(co)) * 1e3, 4),
            "offset_ms_range": round(float(co.max() - co.min()) * 1e3, 4),
            "rtt_ms_p5": round(float(np.percentile(dly, 5)) * 1e3, 4)}
    return (lambda tt: np.interp(np.asarray(tt, float), ct, co)), info


def load_events(path):
    ev = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ev.setdefault(r["roi"], []).append(float(r["t_s"]))
    return {k: np.array(sorted(v)) for k, v in ev.items()}


def mixer_block_ms(onsets_csv):
    """Mixer block size detected by audio_onsets.py (sidecar .meta.json), or 0 if unknown."""
    try:
        with open(onsets_csv[:-4] + ".meta.json") as f:
            mb = json.load(f).get("mixer_block")
        return float(mb["ms"]) if isinstance(mb, dict) else 0.0
    except (OSError, ValueError, KeyError):
        return 0.0


def load_wall_onsets(path):
    with open(path, newline="") as f:
        return np.array(sorted(float(r["t_wall_s"]) for r in csv.DictReader(f)))


def approx_start(video, start):
    if start:
        d = dt.datetime.fromisoformat(start)
        return (d if d.tzinfo else d.astimezone()).timestamp()
    if video:
        m = re.search(r"(\d{4}-\d{2}-\d{2})[ _](\d{2})-(\d{2})-(\d{2})", os.path.basename(video))
        if m:
            d = dt.datetime.fromisoformat(f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}")
            return d.astimezone().timestamp()
    raise SystemExit("need --*-start or an OBS-style file name (YYYY-MM-DD HH-MM-SS) for --*-video")


def video_to_wall(flash_t, start_s):
    """Fit wall = a * video_t + b using flash onsets that occur at integer UTC seconds."""
    if len(flash_t) < 5:
        raise SystemExit("fewer than 5 flash onsets found - is the sync_flash overlay in the recording?")
    est = start_s + flash_t
    # OBS file names truncate the start time -> true wall >= est. Integer-second ambiguity is
    # resolved later by resolve_second_shift() (tries -1/0/+1 s against the press times).
    k = np.ceil(est - 0.03)
    a, b = np.polyfit(flash_t, k, 1)
    resid = (a * flash_t + b - k) * 1000
    # drop outliers (missed / double flashes) and refit
    m = np.abs(resid) < max(3 * np.std(resid), 5)
    a, b = np.polyfit(flash_t[m], k[m], 1)
    resid = (a * flash_t[m] + b - k[m]) * 1000
    return (lambda t: a * np.asarray(t) + b), {"flashes": int(m.sum()), "slope": float(a),
                                                 "fit_resid_ms_std": round(float(np.std(resid)), 3)}


# ----------------------------------------------------------------------------- matching
def match(press, onsets, wmin_ms, wmax_ms):
    d = np.full(len(press), np.nan)
    j = 0
    for i, p in enumerate(press):
        lo, hi = p + wmin_ms / 1000, p + wmax_ms / 1000
        k = np.searchsorted(onsets, lo)
        if k < len(onsets) and onsets[k] <= hi:
            d[i] = (onsets[k] - p) * 1000
    return d


def resolve_second_shift(press, onsets_ref, wmin, wmax):
    """Pick the whole-second shift (-1/0/+1) of a video's time mapping that makes most presses
    match an onset (a wrong second leaves almost nothing inside the search window)."""
    best = None
    for s in (0, -1, 1):
        d = match(press, onsets_ref + s, wmin, wmax)
        n = int(np.isfinite(d).sum())
        iqr = float(np.subtract(*np.nanpercentile(d, [75, 25]))) if n > 3 else 1e9
        key = (n, -iqr)
        if best is None or key > best[0]:
            best = (key, s)
    return best[1]


# ----------------------------------------------------------------------------- model fit
from functools import lru_cache


@lru_cache(maxsize=20000)
def _pdf_grid(T, F, sigma, K, dx):
    """PDF of sum of K U(0,T) + sum_j U(0,F_j) + N(0,sigma). F is a tuple of frame periods (ms)."""
    n = int((K * T + sum(F) + 8 * sigma) / dx) + 8
    x = np.arange(n) * dx
    pdf = np.zeros(n); pdf[0] = 1.0
    def box(w):
        m = max(1, int(round(w / dx)))
        return np.ones(m) / m
    for _ in range(K):
        pdf = np.convolve(pdf, box(T))[:n]
    for Fj in F:
        pdf = np.convolve(pdf, box(Fj))[:n]
    g = np.exp(-0.5 * ((np.arange(-4 * sigma, 4 * sigma + dx, dx)) / max(sigma, dx)) ** 2)
    g /= g.sum()
    pdf = np.convolve(pdf, g)
    shift = len(g) // 2
    pdf = pdf[:n + shift]
    x = np.arange(len(pdf)) * dx - shift * dx  # gaussian centred
    return x, pdf / (pdf.sum() * dx)


def fit_model(d, F, K, T_grid, sig_grid, dx=0.1, eps=0.01):
    """Max-likelihood over (c, T, sigma) for a given K. Returns best params and LL."""
    d = np.asarray(d)
    # pad on the left by the widest model support so the fitted offset c never wraps around
    pad = K * max(T_grid) + sum(F) + 8 * max(sig_grid) + 5
    lo = d.min() - pad
    span = d.max() - lo + 1.0
    nb = int(span / dx) + 1
    h = np.bincount(((d - lo) / dx).astype(int), minlength=nb).astype(float)
    best = (-np.inf, None)
    W = span + 300  # outlier floor width (ms)
    for T in T_grid:
        for s in sig_grid:
            x, pdf = _pdf_grid(float(T), tuple(float(v) for v in F), float(s), int(K), float(dx))
            lp = np.log((1 - eps) * pdf + eps / W)
            floor = np.log(eps / W)
            # LL(shift) = sum_i lp[(d_i - c) index]; correlate histogram with lp via FFT
            L = len(h) + len(lp)
            nfft = 1 << int(np.ceil(np.log2(L)))
            # place lp so that index j <-> x value x[j]; c = lo + shift*dx - x[0]
            corr = np.fft.irfft(np.fft.rfft(h, nfft) * np.conj(np.fft.rfft(lp - floor, nfft)), nfft)
            # corr[m] = sum_j h[j+m] (lp-floor)[j]  -> data bin j+m aligned with pdf bin j
            ll = corr[:len(h)] + floor * len(d)
            m = int(np.argmax(ll))
            if ll[m] > best[0]:
                c = lo + m * dx - x[0]
                best = (float(ll[m]), {"c_ms": round(c, 2), "T_ms": float(T), "sigma_ms": float(s), "K": K})
    return best


def fit_all(d, F, boot=60, seed=0):
    d = d[np.isfinite(d)]
    if len(d) < 30:
        return {"error": f"only {len(d)} matched presses (need >= 30, ideally 200+)"}
    T_grid = np.arange(2.0, 150.0, 0.5); sig = np.array([0.3, 0.7, 1.2, 2, 3, 5, 8])
    out = {}
    for K in (1, 2):
        ll, p = fit_model(d, F, K, T_grid, sig)
        p["LL"] = round(ll, 2)
        out[f"K{K}"] = p
    bestK = 1 if out["K1"]["LL"] >= out["K2"]["LL"] - 2 else 2  # prefer simpler unless clearly worse
    rng = np.random.default_rng(seed)
    T0 = out[f"K{bestK}"]["T_ms"]
    Tg = np.arange(max(2, T0 - 15), T0 + 15, 0.5); sg = sig   # same sigma grid as the main fit
    bs = []
    for _ in range(boot):
        _, p = fit_model(rng.choice(d, len(d)), F, bestK, Tg, sg)
        bs.append(p["T_ms"])
    out["best_K"] = bestK
    out["T_ms"] = T0
    out["T_ms_CI95"] = [round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
    out["implied_Hz"] = round(1000 / T0, 2)
    out["n"] = int(len(d))
    return out


# ----------------------------------------------------------------------------- periodicity
def rayleigh(t, fmin=5, fmax=130, step=0.01):
    t = np.asarray(t) - np.min(t)
    f = np.arange(fmin, fmax, step)
    z = np.empty_like(f)
    for i in range(0, len(f), 500):
        ph = 2 * np.pi * f[i:i + 500, None] * t[None, :]
        z[i:i + 500] = (np.cos(ph).sum(1) ** 2 + np.sin(ph).sum(1) ** 2) / len(t)
    return f, z


def peaks(f, z, n=5):
    out = []
    for i in np.argsort(z)[::-1]:
        if all(abs(f[i] - q) > 0.6 for q, _ in out):
            out.append((round(float(f[i]), 2), round(float(z[i]), 1)))
        if len(out) == n:
            break
    return out


def frame_artifact(freq, fps, tol=0.05):
    """True if freq ~ fps/k for small integer k (the frame grid itself creates such peaks)."""
    if not fps:
        return False
    return any(abs(freq - fps / k) < tol for k in range(1, 30))


# War Thunder mixes sound in 1024-sample blocks (48000/1024 = 46.875 Hz, seen in every session), and WASAPI
# delivers 256-sample buffers. Sound onsets lock to these grids, their harmonics and subharmonics.
AUDIO_BLOCK_HZ = (48000 / 1024, 48000 / 256)


def audio_block_artifact(freq, tol=0.05):
    return any(abs(freq - b * m / k) < tol for b in AUDIO_BLOCK_HZ for m in range(1, 5) for k in range(1, 9))


# ----------------------------------------------------------------------------- packets (optional)
def packet_layer(pcap, clock_fn, press_ref=None, onset_ref=None):
    import analyze_pcap as ap  # from ../../tools
    rows = ap.load_packets(pcap)
    best, flows = ap.pick_flows(rows)
    if not best:
        return {"error": "no game flow found"}
    fl = flows[best]
    up = np.array(sorted(t for t, _ in fl["up"])); dn = np.array(sorted(t for t, _ in fl["down"]))
    up = up + clock_fn(up); dn = dn + clock_fn(dn)
    res = {"flow": best, "up_pps": round(len(up) / (up[-1] - up[0]), 2) if len(up) > 1 else None,
           "down_pps": round(len(dn) / (dn[-1] - dn[0]), 2) if len(dn) > 1 else None}
    if press_ref is not None and len(up):
        k = np.searchsorted(up, press_ref)
        ok = k < len(up)
        dd = (up[k[ok]] - press_ref[ok]) * 1000
        res["press_to_next_upstream_ms"] = {q: round(float(np.percentile(dd, p)), 2) for q, p in (("p5", 5), ("p50", 50), ("p95", 95))}
    if onset_ref is not None and len(dn):
        k = np.searchsorted(dn, onset_ref) - 1
        ok = k >= 0
        dd = (onset_ref[ok] - dn[k[ok]]) * 1000
        res["last_downstream_to_onset_ms"] = {q: round(float(np.percentile(dd, p)), 2) for q, p in (("p5", 5), ("p50", 50), ("p95", 95))}
    f, z = rayleigh(dn[: min(len(dn), 20000)])
    res["downstream_rayleigh_peaks_hz"] = peaks(f, z)
    return res


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shooter-inputs", required=True)
    ap.add_argument("--fire-button", default="mouse_left")
    ap.add_argument("--shooter-clock"); ap.add_argument("--observer-clock")
    ap.add_argument("--observer-wall-onsets", help="AUDIO mode: onsets CSV from audio_onsets.py (t_wall_s) - preferred")
    ap.add_argument("--shooter-wall-onsets", help="AUDIO mode: shooter's own gunshot onsets (press -> own shot)")
    ap.add_argument("--audio-block-ms", type=float, default=0,
                    help="model an extra uniform wait for the game's audio mixing block (0 = let the fit absorb it)")
    ap.add_argument("--observer-events", help="VIDEO mode: events.csv from video_event_timer.py")
    ap.add_argument("--observer-video"); ap.add_argument("--observer-start")
    ap.add_argument("--observer-fps", type=float, default=0, help="VIDEO mode: recording fps")
    ap.add_argument("--observer-game-fps", type=float, default=144, help="game frame rate on observer PC (FPS cap / refresh)")
    ap.add_argument("--remote-roi", default="enemy_fire", help="ROI on observer video where the shooter's fire appears")
    ap.add_argument("--flash-roi", default="flash")
    ap.add_argument("--shooter-events"); ap.add_argument("--shooter-video"); ap.add_argument("--shooter-start")
    ap.add_argument("--shooter-fps", type=float, default=0, help="shooter recording fps (default = observer's)")
    ap.add_argument("--shooter-game-fps", type=float, default=144, help="game frame rate on shooter PC")
    ap.add_argument("--local-rois", default="muzzle", help="ROIs on the shooter's own video (e.g. muzzle,hit)")
    ap.add_argument("--pcap-shooter"); ap.add_argument("--pcap-observer")
    ap.add_argument("--min-gap-ms", type=float, default=300, help="press must follow >= this much idle time")
    ap.add_argument("--window-ms", default="5,600", help="search window after press, ms")
    ap.add_argument("--boot", type=int, default=60)
    ap.add_argument("--out", default="analysis/shooting")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    wmin, wmax = map(float, a.window_ms.split(","))

    sh_clock, sh_clk_info = load_clock(a.shooter_clock)
    ob_clock, ob_clk_info = load_clock(a.observer_clock)
    all_down, press_local = load_inputs(a.shooter_inputs, a.fire_button, a.min_gap_ms)
    press = press_local + sh_clock(press_local)                     # -> reference clock

    audio = bool(a.observer_wall_onsets)
    if audio:
        # AUDIO mode: onsets already carry wall-clock times (sample clock fitted in audio_onsets.py)
        rem_local = load_wall_onsets(a.observer_wall_onsets)
        rem = rem_local + ob_clock(rem_local)
        blk = a.audio_block_ms or mixer_block_ms(a.observer_wall_onsets)
        vinfo = {"mode": "audio", "onsets": int(len(rem)), "mixer_block_ms": blk}
        F_obs = (1000 / a.observer_game_fps,) + ((blk,) if blk else ())
        # artifact sources: game frame grid and the audio mixer block grid (and their subharmonics)
        art_rates = [a.observer_game_fps] + ([1000 / blk] if blk else [])
        fmax = 130
    else:
        if not (a.observer_events and a.observer_fps):
            raise SystemExit("give --observer-wall-onsets (audio) or --observer-events + --observer-fps (video)")
        ev = load_events(a.observer_events)
        if a.flash_roi not in ev or a.remote_roi not in ev:
            raise SystemExit(f"observer events need ROIs '{a.flash_roi}' and '{a.remote_roi}', found {list(ev)}")
        v2w, vinfo = video_to_wall(ev[a.flash_roi], approx_start(a.observer_video, a.observer_start))
        rem_local = v2w(ev[a.remote_roi])
        rem = rem_local + ob_clock(rem_local)
        shift = resolve_second_shift(press, rem, wmin, wmax)
        rem = rem + shift
        vinfo["second_shift_applied"] = shift
        # two quantization boxes on the observer side: game frame (update waits for next game frame)
        # and video capture frame
        F_obs = (1000 / a.observer_fps, 1000 / a.observer_game_fps)
        art_rates, fmax = [a.observer_fps], min(130, a.observer_fps / 2 - 0.5)

    d_rem = match(press, rem, wmin, wmax)
    summary = {"presses_total": int(len(all_down)), "presses_isolated": int(len(press)),
               "matched_remote": int(np.isfinite(d_rem).sum()),
               "observer_video_sync": vinfo, "shooter_clock": sh_clk_info, "observer_clock": ob_clk_info,
               "remote_delay_ms": {q: round(float(np.nanpercentile(d_rem, p)), 2) for q, p in
                                   (("p5", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95))} if np.isfinite(d_rem).any() else None,
               "remote_fit": fit_all(d_rem, F_obs, a.boot)}
    # video: scan only below the video's Nyquist frequency (above it, peaks are aliases fps - f)
    # fold only the onsets that were MATCHED to a press: the recording also contains other sounds
    # (e.g. the observer's own shots in a later run), whose grid would otherwise fake a verdict
    ok = np.isfinite(d_rem)
    f, z = rayleigh(press[ok] + d_rem[ok] / 1000, fmax=fmax)
    pk = peaks(f, z)
    summary["remote_onset_rayleigh_peaks_hz"] = [{"hz": h, "Z": s, "frame_artifact": any(frame_artifact(h, r) for r in art_rates) or (audio and audio_block_artifact(h))}
                                                 for h, s in pk]

    local = {}
    if a.shooter_wall_onsets:
        on_local = load_wall_onsets(a.shooter_wall_onsets); on = on_local + sh_clock(on_local)
        dloc = match(press, on, 1, wmax)
        local["sound"] = dloc
        sblk = a.audio_block_ms or mixer_block_ms(a.shooter_wall_onsets)
        Fs_a = (1000 / a.shooter_game_fps,) + ((sblk,) if sblk else ())
        s_art = [a.shooter_game_fps] + ([1000 / sblk] if sblk else [])
        summary["shooter_mixer_block_ms"] = sblk
        summary["local_sound_delay_ms"] = {q: round(float(np.nanpercentile(dloc, p)), 2) for q, p in
                                           (("p5", 5), ("p50", 50), ("p95", 95))} if np.isfinite(dloc).any() else None
        summary["local_sound_fit"] = fit_all(dloc, Fs_a, a.boot)
        okl = np.isfinite(dloc)
        fl, zl = rayleigh(press[okl] + dloc[okl] / 1000, fmax=130)
        summary["local_sound_rayleigh_peaks_hz"] = [{"hz": h, "Z": s, "frame_artifact": any(frame_artifact(h, r) for r in s_art) or audio_block_artifact(h)}
                                                   for h, s in peaks(fl, zl)]
    if a.shooter_events:
        sev = load_events(a.shooter_events)
        s2w, sinfo = video_to_wall(sev[a.flash_roi], approx_start(a.shooter_video, a.shooter_start))
        summary["shooter_video_sync"] = sinfo
        Fs = (1000 / (a.shooter_fps or a.observer_fps), 1000 / a.shooter_game_fps)
        sh_shift = None
        for roi in filter(None, a.local_rois.split(",")):
            if roi not in sev:
                continue
            on_local = s2w(sev[roi]); on = on_local + sh_clock(on_local)
            if sh_shift is None:   # resolve once, on the first local ROI (muzzle)
                sh_shift = resolve_second_shift(press, on, 1, wmax)
                sinfo["second_shift_applied"] = sh_shift
            on = on + sh_shift
            dloc = match(press, on, 1, wmax)
            local[roi] = dloc
            summary[f"local_{roi}_delay_ms"] = {q: round(float(np.nanpercentile(dloc, p)), 2) for q, p in
                                               (("p5", 5), ("p50", 50), ("p95", 95))} if np.isfinite(dloc).any() else None
            summary[f"local_{roi}_fit"] = fit_all(dloc, Fs, a.boot)
            sfps = a.shooter_fps or a.observer_fps
            okv = np.isfinite(dloc)
            fl, zl = rayleigh(press[okv] + dloc[okv] / 1000, fmax=min(130, sfps / 2 - 0.5))
            summary[f"local_{roi}_rayleigh_peaks_hz"] = [{"hz": h, "Z": s, "frame_artifact": frame_artifact(h, sfps)}
                                                        for h, s in peaks(fl, zl)]

    if a.pcap_shooter:
        summary["packets_shooter"] = packet_layer(a.pcap_shooter, sh_clock, press_ref=press)
    if a.pcap_observer:
        summary["packets_observer"] = packet_layer(a.pcap_observer, ob_clock, onset_ref=rem)

    summary["verdict"] = verdict(summary["remote_fit"], summary["remote_onset_rayleigh_peaks_hz"])
    for roi in local:
        summary[f"local_{roi}_verdict"] = verdict(summary[f"local_{roi}_fit"], summary[f"local_{roi}_rayleigh_peaks_hz"])

    # ---------------- outputs
    with open(os.path.join(a.out, "presses.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["press_ref_s", "remote_delay_ms"] + [f"local_{k}_ms" for k in local])
        for i in range(len(press)):
            w.writerow([f"{press[i]:.6f}", f"{d_rem[i]:.3f}"] + [f"{local[k][i]:.3f}" for k in local])
    with open(os.path.join(a.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    nplots = 2 + len(local)
    fig, ax = plt.subplots(nplots, 1, figsize=(11, 3.4 * nplots))
    def hist_with_fit(axx, d, F, fit, title):
        d = d[np.isfinite(d)]
        if not len(d):
            axx.set_title(title + " (no data)"); return
        axx.hist(d, bins=np.arange(np.floor(d.min()) - 2, np.ceil(d.max()) + 2, 1.0), density=True, alpha=.6)
        if "best_K" in fit:
            p = fit[f"K{fit['best_K']}"]
            x, pdf = _pdf_grid(float(p["T_ms"]), tuple(float(v) for v in F), float(p["sigma_ms"]), int(p["K"]), 0.1)
            axx.plot(x + p["c_ms"], pdf, "r", lw=1.5,
                     label=f"fit: K={p['K']} T={p['T_ms']} ms ({1000 / p['T_ms']:.1f} Hz) CI {fit['T_ms_CI95']}")
            axx.legend()
        axx.set_title(title); axx.set_xlabel("ms after fire press")
    hist_with_fit(ax[0], d_rem, F_obs, summary["remote_fit"],
                  "Press -> shot HEARD on OBSERVER PC" if audio else "Press -> shot visible on OBSERVER screen")
    for i, (k, dl) in enumerate(local.items(), start=1):
        if k == "sound":
            Fk = Fs_a
        else:
            Fk = (1000 / (a.shooter_fps or a.observer_fps), 1000 / a.shooter_game_fps)
        hist_with_fit(ax[i], dl, Fk, summary[f"local_{k}_fit"], f"Press -> {k} on SHOOTER side")
    ax[-1].plot(f, z, lw=.6); ax[-1].set_title("Rayleigh phase-folding of observer onset times (red = frame-rate artifact zones)")
    for rr in art_rates:
        for k in range(1, 30):
            ax[-1].axvspan(rr / k - .05, rr / k + .05, color="r", alpha=.3)
    for c in CANDIDATES_HZ:
        ax[-1].axvline(c, ls=":", color="k", lw=.6)
    ax[-1].set_xlabel("Hz")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "shooting_latency.png"), dpi=110); plt.close(fig)

    write_report(a, summary, local)
    print(json.dumps({k: summary[k] for k in ("presses_isolated", "matched_remote", "remote_delay_ms", "verdict")}, indent=2))
    print("->", a.out)


def verdict(fit, fold_peaks):
    """Combine the two independent period estimates.
    * spread fit (distribution width) - fails when two waits interact (e.g. client grid vs server grid at
      an unlucky phase), but needs no phase locking;
    * phase folding (strongest non-artifact peak) - robust to that, but needs onsets phase-locked to a
      fixed grid (true for a fixed server tick).
    """
    fold = next((p for p in fold_peaks if not p["frame_artifact"]), None)
    v = {"fold_period_ms": round(1000 / fold["hz"], 2) if fold else None, "fold_Z": fold["Z"] if fold else None,
         "fit_period_ms": fit.get("T_ms")}
    strong = fold is not None and fold["Z"] >= 15          # Rayleigh Z >= 15 -> p < 3e-7 for one test
    if "T_ms" in fit and strong:
        # accept harmonics: fold may see 2x/3x the fundamental if waits stack
        r = fit["T_ms"] / v["fold_period_ms"]
        if abs(r - round(r)) < 0.12 and round(r) >= 1:
            v.update(period_ms=v["fold_period_ms"] * round(r), status="CONSISTENT: spread fit and phase folding agree")
        else:
            v.update(period_ms=v["fold_period_ms"],
                     status="FOLD-ONLY: phase folding is strong but the spread fit disagrees (likely two interacting waits) - trust the fold period")
    elif strong:
        v.update(period_ms=v["fold_period_ms"], status="FOLD-ONLY: no usable spread fit")
    elif "T_ms" in fit:
        v.update(period_ms=fit["T_ms"], status="FIT-ONLY: no strong phase-locked peak (tick may not be phase-stable, or too few presses)")
    else:
        v.update(period_ms=None, status="INCONCLUSIVE: need more presses")
    if v.get("period_ms"):
        v["implied_Hz"] = round(1000 / v["period_ms"], 2)
    return v


def write_report(a, s, local):
    rf = s["remote_fit"]
    L = ["# Shooting latency report", "",
         f"- Presses: {s['presses_total']} total, {s['presses_isolated']} isolated, {s['matched_remote']} matched on the observer video",
         f"- Observer timing source: {s['observer_video_sync']}",
         f"- Clock (shooter vs Salty): {s['shooter_clock'] or 'is reference'}; (observer vs Salty): {s['observer_clock'] or 'is reference'}",
         "", f"## VERDICT: tick period {s['verdict'].get('period_ms')} ms ≈ {s['verdict'].get('implied_Hz')} Hz", f"_{s['verdict']['status']}_", "",
         "## Press → visible on observer", f"Delay percentiles (ms): {s['remote_delay_ms']}",
         "(absolute delays are relative to the flash overlay's own display latency; the tick period is unaffected)", ""]
    if "error" in rf:
        L.append(f"Fit: {rf['error']}")
    else:
        L += [f"**Spread fit: T = {rf['T_ms']} ms ≈ {rf['implied_Hz']} Hz (95 % CI {rf['T_ms_CI95']} ms), K = {rf['best_K']} uniform wait(s), n = {rf['n']}**",
              f"- one-wait model: {rf['K1']}", f"- two-wait model: {rf['K2']}",
              "- Interpretation: T is the period of the tick the shot has to wait for. "
              "K = 2 means two independent waits of the same period (e.g. client fire grid + server tick)."]
    L += ["", "## Phase-folding peaks (observer onsets)"]
    for p in s["remote_onset_rayleigh_peaks_hz"]:
        L.append(f"- {p['hz']} Hz (Z={p['Z']}){'  ⚠ frame-rate artifact zone (fps/k)' if p['frame_artifact'] else ''}")
    for k in local:
        L += ["", f"## Press → {k} on shooter screen", f"Delays (ms): {s.get(f'local_{k}_delay_ms')}",
              f"Fit: {s.get(f'local_{k}_fit')}"]
    for key in ("packets_shooter", "packets_observer"):
        if key in s:
            L += ["", f"## {key}", "```", json.dumps(s[key], indent=2), "```"]
    L += ["", "![plots](shooting_latency.png)"]
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
