"""18 Nov 2026, ground RB custom battle: you in a plane (2 MGs), Salty in an Ostwind.
Only your PC was recorded. This looks at your own shots (press -> gunshot on your PC)."""
import sys, json, csv, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
D = os.path.join(ROOT, 'data', '20261118', 'DESKTOP-42SCBR7')

ins = [json.loads(l) for l in open(os.path.join(D, 'inputs_desktop-42scbr7_20261118_180447.jsonl'))][1:]
dn = np.array([x['t_wall_ns'] / 1e9 for x in ins if x['down']])
up = np.array([x['t_wall_ns'] / 1e9 for x in ins if not x['down']])
up = np.array([up[up > d][0] if (up > d).any() else np.nan for d in dn])
hold = (up - dn) * 1000
rows = list(csv.DictReader(open(os.path.join(D, 'onsets_all.csv'))))
on = np.array([float(r['t_wall_s']) for r in rows]); st = np.array([float(r['strength']) for r in rows])

print(f'presses {len(dn)}, span {(dn[-1]-dn[0])/60:.1f} min, hold p5/50/95 {np.nanpercentile(hold,[5,50,95]).round(0)} ms')
print(f'onsets {len(on)}, span {(on[-1]-on[0])/60:.1f} min')

def hist(lo, hi, step=10):
    d = []
    for p in dn:
        m = (on > p + lo / 1000) & (on < p + hi / 1000); d += list((on[m] - p) * 1000)
    h, e = np.histogram(d, bins=np.arange(lo, hi + step, step))
    for a, b in zip(e, h):
        print(f'{a:5.0f} {"#" * int(b)} {b}')
print('\nall onsets after each press (ms):'); hist(0, 600)

# background onset rate (Salty's Ostwind + anything else), to judge chance matches
gaps = np.diff(dn)
print('\nbackground onsets per second (between 1 s after a press and the next press):')
bg = sum(((on > a + 1.0) & (on < b)).sum() for a, b in zip(dn[:-1], dn[1:])); bt = sum(max(0, b - a - 1.0) for a, b in zip(dn[:-1], dn[1:]))
print(f'  {bg / bt:.2f} /s')

# first onset per press in a window, and the shot pattern after it
def first(p, lo, hi):
    m = np.where((on > p + lo / 1000) & (on < p + hi / 1000))[0]
    return m[0] if len(m) else -1
LO, HI = float(sys.argv[1]) if len(sys.argv) > 1 else 100, float(sys.argv[2]) if len(sys.argv) > 2 else 260
idx = np.array([first(p, LO, HI) for p in dn])
ok = idx >= 0
d1 = (on[idx[ok]] - dn[ok]) * 1000
print(f'\nfirst onset {LO:.0f}-{HI:.0f} ms: matched {ok.sum()}/{len(dn)}; delay p5/25/50/75/95 {np.percentile(d1,[5,25,50,75,95]).round(1)} IQR {np.subtract(*np.percentile(d1,[75,25])):.1f}')

# spacing between successive onsets inside a burst (double-fire check)
sp = []
for i in idx[ok]:
    j = i
    while j + 1 < len(on) and on[j + 1] - on[j] < 0.12 and on[j + 1] - on[i] < 0.6:
        sp.append((on[j + 1] - on[j]) * 1000); j += 1
sp = np.array(sp)
print('\nintra-burst onset spacing (ms) histogram:')
h, e = np.histogram(sp, bins=np.arange(0, 125, 5))
for a, b in zip(e, h):
    print(f'{a:4.0f} {"#" * int(b // 2)} {b}')

# phase lock of presses vs first-onset delay: blind scan
def rayleigh(t, f):
    ph = 2 * np.pi * f * t; n = len(t)
    return n * (np.cos(ph).mean() ** 2 + np.sin(ph).mean() ** 2)
t_on = on[idx[ok]]
print('\nphase lock of own-shot onsets (Z):', {f: round(rayleigh(t_on, f), 1) for f in [10, 15, 20, 24, 30, 46.875, 48, 60]})
# sawtooth: residual delay vs press phase at f, find best f by min IQR of detrended delay
best = []
for f in np.arange(15, 60.01, 0.01):
    ph = (dn[ok] * f) % 1
    # wait model: delay = c + (1-ph)/f  -> residual = d1 - (1-ph)/f*1000
    r = d1 - ((1 - ph) % 1) / f * 1000
    best.append((np.subtract(*np.percentile(r, [75, 25])), f))
best.sort()
print('best wait frequencies (residual IQR ms, f):', [(round(a, 1), round(b, 2)) for a, b in best[:5]])
iqr24 = [a for a, b in best if abs(b - 24) < 0.005]; iqr48 = [a for a, b in best if abs(b - 48) < 0.005]
print(f'residual IQR at 24 Hz {iqr24[0]:.1f}, at 48 Hz {iqr48[0]:.1f}, raw {np.subtract(*np.percentile(d1,[75,25])):.1f}')
np.save(os.path.join(HERE, 'own.npy'), np.c_[dn[ok], hold[ok], d1])
