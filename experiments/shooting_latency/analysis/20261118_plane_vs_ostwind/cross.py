"""Cross-PC timing for 18 Nov (you: plane, Salty: Ostwind). All times on Salty's clock."""
import sys, os, json, csv
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
from analyze_shooting import load_clock
D = os.path.join(ROOT, 'data', '20261118')
off, _ = load_clock(os.path.join(D, 'DESKTOP-42SCBR7', 'clock_desktop-42scbr7_vs_192-168-1-225_20261118_180447.jsonl'))

def presses(p):
    ins = [json.loads(l) for l in open(p)][1:]
    ev = sorted((x['t_wall_ns'] / 1e9, x['down']) for x in ins if x['btn'] == 'mouse_left')
    dn, hold = [], []
    for i, (t, d) in enumerate(ev):
        if d:
            u = next((t2 for t2, d2 in ev[i + 1:] if not d2), np.nan); dn.append(t); hold.append((u - t) * 1000)
    return np.array(dn), np.array(hold)
def onsets(p):
    r = list(csv.DictReader(open(p))); return np.array([float(x['t_wall_s']) for x in r])

me_dn, me_hold = presses(os.path.join(D, 'DESKTOP-42SCBR7', 'inputs_desktop-42scbr7_20261118_180447.jsonl'))
me_dn = me_dn + off(me_dn)
sa_dn, sa_hold = presses(os.path.join(D, 'SALTY', 'inputs_Salty_20261118_180452.jsonl'))
on_me = onsets(os.path.join(D, 'DESKTOP-42SCBR7', 'onsets_all.csv')); on_me = on_me + off(on_me)
on_sa = onsets(os.path.join(D, 'SALTY', 'onsets_all.csv'))
print(f'clock offset desktop->salty median {np.median(off(on_me)) * 1000:.1f} ms')
print(f'my presses {len(me_dn)} (hold median {np.nanmedian(me_hold):.0f} ms); Salty presses {len(sa_dn)} (hold p5/50/95 {np.nanpercentile(sa_hold,[5,50,95]).round(0)} ms)')

def hist(dn, on, lo, hi, step=10, title=''):
    d = []
    for p in dn:
        m = (on > p + lo / 1000) & (on < p + hi / 1000); d += list((on[m] - p) * 1000)
    h, e = np.histogram(d, bins=np.arange(lo, hi + step, step))
    print(f'\n{title}')
    for a, b in zip(e, h):
        print(f'{a:5.0f} {"#" * int(b)} {b}')
    bgrate = None
    return np.array(d)

def rate_between(on, dn, guard=1.5):
    n = t = 0
    for a, b in zip(dn[:-1], dn[1:]):
        if b - a > guard + 0.5: n += ((on > a + guard) & (on < b)).sum(); t += b - a - guard
    return n / t
print(f'\nbackground onset rate on Salty PC away from my presses: {rate_between(on_sa, me_dn):.2f}/s; on my PC away from Salty presses: {rate_between(on_me, sa_dn):.2f}/s')

hist(me_dn, on_sa, 0, 700, title='YOUR presses -> onsets on SALTY\'s PC (plane heard in the Ostwind)')
hist(sa_dn, on_sa, 0, 400, title='SALTY presses -> onsets on SALTY\'s PC (Ostwind own shot)')
hist(sa_dn, on_me, 0, 700, title='SALTY presses -> onsets on YOUR PC (Ostwind heard in the plane)')
np.savez(os.path.join(HERE, 'cross.npz'), me_dn=me_dn, me_hold=me_hold, sa_dn=sa_dn, sa_hold=sa_hold, on_me=on_me, on_sa=on_sa)
