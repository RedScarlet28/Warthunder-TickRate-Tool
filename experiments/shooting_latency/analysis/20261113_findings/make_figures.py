"""Figures for the 2026-11-13 session. Run from experiments/shooting_latency:
   python analysis/20261113_findings/make_figures.py <path to Salty's data folder>"""
import sys, csv, json, numpy as np
sys.path.insert(0, '.'); import analyze_shooting as A
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
L = "data/20261113/DESKTOP-42SCBR7/"; OUT = "analysis/20261113_findings/"
Z = lambda t, f: np.abs(np.exp(2j*np.pi*f*(t-t[0])).sum())**2/len(t)
# own shots (my PC shooting, 09:10+), my clock
_, pm = A.load_inputs(L+"inputs_desktop-42scbr7_20261113_085750.jsonl", "mouse_left", 300)
on = A.load_wall_onsets(L+"audio_desktop-42scbr7_20261113_085750.onsets.csv")
pm = pm[pm > 1794557400]; dm = A.match(pm, on, 100, 200); k = np.isfinite(dm); pm, dm = pm[k], dm[k]
# remote: Salty shooting, observed on my PC (reference clock)
P = list(csv.DictReader(open("analysis/20261113_salty_shoots/presses.csv")))
ps = np.array([float(r['press_ref_s']) for r in P]); ds = np.array([float(r['remote_delay_ms']) for r in P])
k = np.isfinite(ds); ps, ds = ps[k], ds[k]
res = {}
fig, ax = plt.subplots(2, 2, figsize=(14, 9))
for col, (name, p, d) in enumerate([("YOUR shot, heard on your PC (no network)", pm, dm),
                                     ("SALTY's shot, heard on your PC (via server)", ps, ds)]):
    ph = (p * 24.0) % 1
    a = ax[0, col]; a.scatter(ph * 41.667, d, s=6, alpha=.5)
    bins = np.linspace(0, 1, 13); mid = (bins[1:] + bins[:-1]) / 2
    med = [np.median(d[(ph >= lo) & (ph < hi)]) for lo, hi in zip(bins[:-1], bins[1:])]
    a.plot(mid * 41.667, med, 'r-o', lw=2, label="median per 1/12 of the cycle")
    a.set_xlabel("when the button was pressed within a 24 Hz cycle (ms, shooter's clock)")
    a.set_ylabel("press -> sound (ms)"); a.set_title(name); a.legend()
    a.set_ylim(np.percentile(d, 1) - 10, np.percentile(d, 99) + 10)
    t = p + d / 1000; fs = np.arange(5, 100, 0.005); z = np.array([Z(t, f) for f in fs])
    b = ax[1, col]; b.plot(fs, z, lw=.6)
    for f, lab in [(24, "24"), (48, "48"), (10, "10"), (46.875, "46.875 audio block")]:
        b.axvline(f, color='r' if f != 46.875 else 'gray', ls=':', lw=1); b.text(f, z.max()*.9, lab, rotation=90, fontsize=8)
    b.set_xlabel("Hz"); b.set_ylabel("Rayleigh Z (phase lock of the sound onsets)"); b.set_title("phase folding of the sound onset times")
    res[name] = {"n": int(len(d)), "pct5_25_50_75_95": np.round(np.percentile(d, [5, 25, 50, 75, 95]), 1).tolist(),
                 "Z@24": round(Z(t, 24.0), 1), "Z@48": round(Z(t, 48.0), 1), "Z@10": round(Z(t, 10.0), 1),
                 "Z@46.875": round(Z(t, 46.875), 1), "sawtooth_medians_ms": np.round(med, 1).tolist()}
fig.tight_layout(); fig.savefig(OUT + "tick_sawtooth.png", dpi=95)
json.dump(res, open(OUT + "numbers.json", "w"), indent=1); print(json.dumps(res, indent=1))

# --- remove the shooter's 24 Hz wait and look at what is left (network + server + observer side)
def detrend(p, d, f=24.0):
    T = 1000 / f; best = None
    for phi in np.linspace(0, 1, 400, endpoint=False):
        wait = ((phi - (p * f) % 1) % 1) * T          # time from press to the next tick at phase phi
        r = d - wait; iqr = np.subtract(*np.percentile(r, [75, 25]))
        if best is None or iqr < best[0]: best = (iqr, phi, r)
    return best
out = {}
for name, p, d in [("own", pm, dm), ("remote", ps, ds)]:
    iqr0 = np.subtract(*np.percentile(d, [75, 25])); iqr, phi, r = detrend(p, d)
    out[name] = {"IQR_raw_ms": round(iqr0, 1), "IQR_after_removing_24Hz_wait_ms": round(iqr, 1),
                 "residual_pct5_50_95": np.round(np.percentile(r, [5, 50, 95]), 1).tolist(),
                 "residual_rayleigh": {f: round(Z(p + r / 1000, f), 1) for f in (10.0, 15.0, 20.0, 24.0, 24.318, 30.0, 48.0)}}
    out[name]["residual_top_hz"] = None
    t = p + r / 1000; fs = np.arange(5, 60, 0.002); z = np.array([Z(t, f) for f in fs]); out[name]["residual_top_hz"] = [round(fs[np.argmax(z)], 3), round(z.max(), 1)]
print(json.dumps(out, indent=1)); json.dump(out, open(OUT + "residual.json", "w"), indent=1)
