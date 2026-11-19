"""Packet timing for the 18 Nov session (you in a plane, ground RB custom battle)."""
import os, subprocess, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
PC = os.path.join(ROOT, 'data', '20261118', 'DESKTOP-42SCBR7', 'shoot_DESKTOP-42SCBR7_180446.pcapng')
SRV, PORT, ME = '23.111.31.236', '20054', '192.168.1.216'
cache = os.path.join(HERE, 'pk.npy')
if not os.path.exists(cache):
    out = subprocess.run([r'C:\Program Files\Wireshark\tshark.exe', '-r', PC, '-Y', f'ip.addr=={SRV} && udp.port=={PORT}',
                          '-T', 'fields', '-e', 'frame.time_epoch', '-e', 'ip.src', '-e', 'udp.length'],
                         capture_output=True, text=True).stdout.split('\n')
    a = [(float(t), 1 if s == SRV else 0, int(l)) for t, s, l in (x.split('\t') for x in out if x.strip())]
    np.save(cache, np.array(a))
A = np.load(cache)
def rz(t, f):
    ph = 2 * np.pi * f * t
    return len(t) * (np.cos(ph).mean() ** 2 + np.sin(ph).mean() ** 2)
for name, m in [('server -> you', A[:, 1] == 1), ('you -> server', A[:, 1] == 0)]:
    t = A[m, 0]; dur = t[-1] - t[0]
    g = np.diff(t) * 1000
    h, e = np.histogram(g, bins=np.arange(0, 80.5, 0.5))
    top = np.argsort(h)[::-1][:5]
    print(f'\n{name}: {len(t)} packets, {len(t)/dur:.1f} /s, median size {np.median(A[m,2]):.0f} B')
    print('  most common gaps (ms):', [(round(e[i] + 0.25, 2), int(h[i])) for i in top])
    # blind grid scan on 120 s windows (clock drift between PC and server makes long windows smear)
    W = 120; res = []
    for s in np.arange(t[0], t[-1] - W, W):
        tw = t[(t >= s) & (t < s + W)]
        fs = np.arange(15, 70, 0.002); z = np.array([rz(tw, f) for f in fs])
        res.append((fs[z.argmax()], z.max(), rz(tw, 24.0), rz(tw, 48.0)))
    res = np.array(res)
    print('  per-120 s window: best grid f (Hz) =', np.round(res[:, 0], 2))
    print('  Z at best =', np.round(res[:, 1]).astype(int), ' (N per window ~', int(len(t) / dur * W), ')')
    # fraction of packets on the best grid, per window
    on_grid = []
    for (f, *_), s in zip(res, np.arange(t[0], t[-1] - W, W)):
        tw = t[(t >= s) & (t < s + W)]; ph = (tw * f) % 1
        c = np.angle(np.exp(2j * np.pi * ph).mean()) / (2 * np.pi) % 1
        d = ((ph - c + 0.5) % 1 - 0.5) / f * 1000
        on_grid.append((np.abs(d) < 3).mean())
    print('  share within +-3 ms of that grid =', np.round(on_grid, 2))
