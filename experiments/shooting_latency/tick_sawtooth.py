"""Tick sawtooth test: does the press -> sound delay depend on WHEN within a tick cycle the press happened?

If shots wait for the next tick of a clock running at f on the SHOOTER's PC, the delay falls 1 ms per ms
across the cycle and jumps up by one period at the tick. This tool:
  * scans f (default 15-60 Hz) for the frequency that best removes that wait (smallest residual IQR),
  * gives Rayleigh phase-lock Z of the sound onsets at chosen frequencies,
  * plots delay vs. press phase at the best f and at 24 Hz.

Inputs: one or more "sets", each a CSV with columns press_s,delay_ms (presses.csv from analyze_shooting.py
works: press_ref_s,remote_delay_ms), or an own-shot set built from inputs + onsets on the same PC:
  python tick_sawtooth.py --own INPUTS.jsonl ONSETS.csv --from HH:MM --to HH:MM --label "my own shot" \
                          --remote analysis/run/presses.csv --label2 "Salty -> me" --out analysis/run/sawtooth
Times for --own are on that PC's clock (that is the clock the shooter's tick runs on).
"""
import argparse, csv, datetime as dt, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_shooting as A


def Z(t, f):
    t = np.asarray(t) - np.min(t)
    return float(np.abs(np.exp(2j * np.pi * f * t).sum()) ** 2 / len(t))


def residual_iqr(p, d, f, nphi=120):
    T = 1000 / f; best = (1e9, 0.0)
    for phi in np.linspace(0, 1, nphi, endpoint=False):
        r = d - ((phi - (p * f) % 1) % 1) * T
        q = np.subtract(*np.percentile(r, [75, 25]))
        if q < best[0]: best = (q, phi)
    return best


def hhmm(day_ref, s):
    h, m = map(int, s.split(":"))
    d = dt.datetime.fromtimestamp(day_ref)
    return d.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def analyse(label, p, d, fmin, fmax):
    o = np.argsort(p); p, d = p[o], d[o]
    fs = np.arange(fmin, fmax, 0.05)
    q = np.array([residual_iqr(p, d, f, 60)[0] for f in fs])
    f0 = fs[np.argmin(q)]
    fine = np.arange(f0 - 0.1, f0 + 0.1, 0.002)
    qf = np.array([residual_iqr(p, d, f)[0] for f in fine]); fbest = float(fine[np.argmin(qf)])
    t = p + d / 1000
    out = {"label": label, "n": int(len(d)),
           "delay_pct_5_25_50_75_95": np.round(np.percentile(d, [5, 25, 50, 75, 95]), 1).tolist(),
           "IQR_raw_ms": round(float(np.subtract(*np.percentile(d, [75, 25]))), 1),
           "best_wait_freq_hz": round(fbest, 3), "IQR_after_removing_best_wait": round(float(qf.min()), 1),
           "IQR_after_removing_24Hz_wait": round(residual_iqr(p, d, 24.0)[0], 1),
           "onset_Z": {str(f): round(Z(t, f), 1) for f in (10, 15, 20, 24, 30, 46.875, 48, 60)},
           "press_Z_at_24": round(Z(p, 24.0), 1)}
    return out, (fs, q), (p, d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--own", nargs=2, metavar=("INPUTS", "ONSETS"))
    ap.add_argument("--from", dest="t_from"); ap.add_argument("--to", dest="t_to")
    ap.add_argument("--own-window-ms", default="60,300")
    ap.add_argument("--fire-button", default="mouse_left")
    ap.add_argument("--label", default="own shot (same PC)")
    ap.add_argument("--remote", help="presses.csv from analyze_shooting.py")
    ap.add_argument("--label2", default="remote shot (via server)")
    ap.add_argument("--fmin", type=float, default=15); ap.add_argument("--fmax", type=float, default=60)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sets = []
    if a.own:
        _, press = A.load_inputs(a.own[0], a.fire_button, 300)
        if a.t_from: press = press[press >= hhmm(press[0], a.t_from)]
        if a.t_to: press = press[press < hhmm(press[0], a.t_to)]
        on = A.load_wall_onsets(a.own[1]); w0, w1 = map(float, a.own_window_ms.split(","))
        d = A.match(press, on, w0, w1); k = np.isfinite(d)
        # own-shot delays: drop the far tail (later rounds / other sounds) by a robust window around the median
        med = np.median(d[k]); k &= np.abs(d - med) < 80
        sets.append((a.label, press[k], d[k]))
    if a.remote:
        rows = list(csv.DictReader(open(a.remote)))
        p = np.array([float(r["press_ref_s"]) for r in rows]); d = np.array([float(r["remote_delay_ms"]) for r in rows])
        k = np.isfinite(d); sets.append((a.label2, p[k], d[k]))
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, len(sets), figsize=(7 * len(sets), 9), squeeze=False)
    res = []
    for c, (label, p, d) in enumerate(sets):
        out, (fs, q), (p, d) = analyse(label, p, d, a.fmin, a.fmax); res.append(out)
        f = out["best_wait_freq_hz"]; T = 1000 / f; ph = (p * f) % 1
        bins = np.linspace(0, 1, 13); mid = (bins[1:] + bins[:-1]) / 2
        med = [np.median(d[(ph >= lo) & (ph < hi)]) if np.any((ph >= lo) & (ph < hi)) else np.nan for lo, hi in zip(bins[:-1], bins[1:])]
        x = ax[0, c]; x.scatter(ph * T, d, s=6, alpha=.5); x.plot(mid * T, med, "r-o", lw=2)
        x.set_title(f"{label}: delay vs press phase at {f:.3f} Hz"); x.set_xlabel("press time within the cycle (ms)"); x.set_ylabel("press -> sound (ms)")
        x.set_ylim(np.percentile(d, 1) - 10, np.percentile(d, 99) + 10)
        y = ax[1, c]; y.plot(fs, q); y.axvline(24, color="r", ls=":"); y.axvline(48, color="r", ls=":")
        y.set_xlabel("assumed tick frequency (Hz)"); y.set_ylabel("residual IQR after removing the wait (ms)")
        y.set_title("lower = this frequency explains the delay better")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "sawtooth.png"), dpi=90)
    json.dump(res, open(os.path.join(a.out, "sawtooth.json"), "w"), indent=1)
    print(json.dumps(res, indent=1)); print("->", a.out)


if __name__ == "__main__":
    main()
