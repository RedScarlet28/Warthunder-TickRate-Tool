#!/usr/bin/env python3
"""
Analyse a War Thunder packet capture: find the game-server UDP flow and measure
send rates, inter-arrival structure, periodicity (tick candidates), bursts and gaps.

Requires: tshark on PATH or in Program Files, numpy, matplotlib.
Usage:
    python -I tools/analyze_pcap.py capture.pcapng --out analysis/session_x/pcA
    python -I tools/analyze_pcap.py capture.pcapng --t0 "2026-11-14T19:03:00" --t1 "2026-11-14T19:06:00"
    python -I tools/analyze_pcap.py capture.pcapng --server 1.2.3.4:20010     # force a flow
    python -I tools/analyze_pcap.py capture.pcapng --windows 30            # per-30 s stats (state changes)

Outputs: summary.json, flows.csv, and PNG plots (rate over time, inter-arrival histogram,
periodogram / Rayleigh scan, packet-size distribution) for each direction.
"""
import argparse, csv, datetime as dt, ipaddress, json, os, shutil, subprocess, sys
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def find_tshark():
    for p in (shutil.which("tshark"), r"C:\Program Files\Wireshark\tshark.exe",
              r"C:\Program Files (x86)\Wireshark\tshark.exe"):
        if p and os.path.exists(p):
            return p
    sys.exit("tshark not found")


def load_packets(pcap):
    cmd = [find_tshark(), "-r", pcap, "-Y", "udp", "-T", "fields", "-E", "separator=,",
           "-e", "frame.time_epoch", "-e", "ip.src", "-e", "ip.dst", "-e", "ipv6.src", "-e", "ipv6.dst",
           "-e", "udp.srcport", "-e", "udp.dstport", "-e", "udp.length"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        p = line.split(",")
        if len(p) < 8 or not p[0]:
            continue
        src = p[1] or p[3]; dst = p[2] or p[4]
        try:
            rows.append((float(p[0]), src, dst, int(p[5]), int(p[6]), int(p[7] or 0)))
        except ValueError:
            continue
    return rows


def is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_link_local or a.is_multicast or a.is_loopback
    except ValueError:
        return True


def pick_flows(rows, force=None):
    """Group by remote endpoint (public IP:port). Return {remote: {'down':[(t,len)], 'up':[...]}}."""
    flows = defaultdict(lambda: {"down": [], "up": [], "local": None})
    for t, s, d, sp, dpt, ln in rows:
        if not is_private(s) and is_private(d):
            key = f"{s}:{sp}"; flows[key]["down"].append((t, ln)); flows[key]["local"] = f"{d}:{dpt}"
        elif is_private(s) and not is_private(d):
            key = f"{d}:{dpt}"; flows[key]["up"].append((t, ln)); flows[key]["local"] = f"{s}:{sp}"
    if force:
        return force, flows
    # Exclude flows that are certainly not the game: QUIC/HTTP3 (443), STUN/TURN/Teams/WebRTC
    # (3478-3481, 19302-19309), IPsec/VPN (500, 4500), WireGuard default (51820).
    NOT_GAME = {443, 80, 500, 4500, 51820, 3478, 3479, 3480, 3481, 3544} | set(range(19302, 19310))
    cand = {k: v for k, v in flows.items() if int(k.rsplit(":", 1)[1]) not in NOT_GAME
            and len(v["down"]) >= 200 and len(v["up"]) >= 50}  # game traffic: bidirectional, high volume
    best = max(cand, key=lambda k: len(cand[k]["down"]) + len(cand[k]["up"]), default=None)
    return best, flows


def rayleigh_scan(t, fmin=5.0, fmax=130.0, step=0.01):
    """Phase-folding periodicity test: Z(f) = |sum exp(2*pi*i*f*t)|^2 / N. Peaks at the send period."""
    t = np.asarray(t) - t[0]
    freqs = np.arange(fmin, fmax, step)
    z = np.empty_like(freqs)
    chunk = 400
    for i in range(0, len(freqs), chunk):
        f = freqs[i:i + chunk, None]
        ph = 2 * np.pi * f * t[None, :]
        z[i:i + chunk] = (np.cos(ph).sum(1) ** 2 + np.sin(ph).sum(1) ** 2) / len(t)
    return freqs, z


def burst_merge(t, gap_ms=2.0):
    """Packets closer than gap_ms are one 'send event' (a snapshot split across several UDP packets)."""
    if len(t) == 0:
        return np.array([])
    t = np.sort(np.asarray(t))
    keep = np.concatenate([[True], np.diff(t) > gap_ms / 1000])
    return t[keep]


def describe(name, pk, outdir, tag):
    if len(pk) < 20:
        return {"packets": len(pk)}
    t = np.array([p[0] for p in pk]); ln = np.array([p[1] for p in pk])
    dur = t[-1] - t[0]
    ev = burst_merge(t)
    ia = np.diff(ev) * 1000  # ms
    med = float(np.median(ia))
    freqs, z = rayleigh_scan(ev[: min(len(ev), 20000)])
    # Top peaks (excluding near-duplicates / harmonics are reported, interpret manually)
    order = np.argsort(z)[::-1]
    peaks = []
    for i in order:
        if all(abs(freqs[i] - f) > 0.5 for f, _ in peaks):
            peaks.append((float(freqs[i]), float(z[i])))
        if len(peaks) == 6:
            break
    gaps = ia[ia > 3 * med]
    res = {
        "packets": int(len(t)), "send_events": int(len(ev)), "duration_s": round(dur, 3),
        "packets_per_s": round(len(t) / dur, 2), "events_per_s": round(len(ev) / dur, 2),
        "bytes_per_s": round(ln.sum() / dur, 1), "pkt_len_median": float(np.median(ln)),
        "pkt_len_p95": float(np.percentile(ln, 95)),
        "interarrival_ms": {k: round(float(np.percentile(ia, q)), 3) for k, q in
                            (("p1", 1), ("p5", 5), ("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))},
        "implied_rate_from_median_hz": round(1000 / med, 2) if med > 0 else None,
        "jitter_ms_std": round(float(np.std(ia)), 3),
        "rayleigh_top_peaks_hz": peaks,
        "gaps_gt_3x_median": int(len(gaps)), "gap_fraction_time": round(float(gaps.sum() / 1000 / dur), 5),
    }
    # --- plots ---
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))
    sec = np.floor(t - t[0]).astype(int)
    ax[0, 0].plot(np.bincount(sec), lw=0.8); ax[0, 0].set_title(f"{tag} {name}: packets per second")
    ax[0, 0].set_xlabel("s")
    ax[0, 1].hist(ia[ia < 250], bins=500); ax[0, 1].set_title("send-event inter-arrival (ms) — comb spacing = period")
    for hz, c in ((10, "r"), (15, "m"), (20, "y"), (30, "g"), (48, "b"), (60, "c")):
        ax[0, 1].axvline(1000 / hz, color=c, ls="--", lw=0.7, label=f"{hz} Hz")
    ax[0, 1].legend(fontsize=7)
    ax[1, 0].plot(freqs, z, lw=0.6); ax[1, 0].set_title("Rayleigh phase-folding scan (peak = periodic send rate)")
    ax[1, 0].set_xlabel("Hz")
    ax[1, 1].hist(ln, bins=200); ax[1, 1].set_title("UDP payload length (B)")
    fig.tight_layout(); fig.savefig(os.path.join(outdir, f"{tag}_{name}.png"), dpi=110); plt.close(fig)
    return res


def parse_time(s):
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.astimezone()  # local time
    return d.timestamp()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap")
    ap.add_argument("--out", default="analysis/pcap")
    ap.add_argument("--server", help="force remote ip:port")
    ap.add_argument("--t0"); ap.add_argument("--t1")
    ap.add_argument("--windows", type=float, default=0, help="also emit per-window stats (seconds)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = load_packets(a.pcap)
    t0, t1 = parse_time(a.t0), parse_time(a.t1)
    rows = [r for r in rows if (t0 is None or r[0] >= t0) and (t1 is None or r[0] <= t1)]
    best, flows = pick_flows(rows, a.server)
    with open(os.path.join(a.out, "flows.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["remote", "local", "down_pkts", "up_pkts", "first", "last"])
        for k, v in sorted(flows.items(), key=lambda kv: -(len(kv[1]["down"]) + len(kv[1]["up"]))):
            ts = [x[0] for x in v["down"] + v["up"]]
            w.writerow([k, v["local"], len(v["down"]), len(v["up"]), min(ts), max(ts)])
    if not best:
        sys.exit("no candidate game flow found (only QUIC/STUN/VPN traffic?) - see flows.csv, or pass --server ip:port")
    fl = flows[best]
    tag = best.replace(":", "_")
    summary = {"pcap": a.pcap, "server_flow": best, "local": fl["local"],
               "down": describe("down_server_to_client", fl["down"], a.out, tag),
               "up": describe("up_client_to_server", fl["up"], a.out, tag)}
    if a.windows > 0:
        allt = [x[0] for x in fl["down"] + fl["up"]]
        start, end = min(allt), max(allt)
        summary["windows"] = []
        w0 = start
        while w0 < end:
            dn = [p for p in fl["down"] if w0 <= p[0] < w0 + a.windows]
            up = [p for p in fl["up"] if w0 <= p[0] < w0 + a.windows]
            def quick(pk):
                if len(pk) < 5:
                    return None
                ev = burst_merge([p[0] for p in pk]); ia = np.diff(ev) * 1000
                return {"pps": round(len(pk) / a.windows, 1), "eps": round(len(ev) / a.windows, 1),
                        "ia_p50": round(float(np.median(ia)), 2), "ia_p95": round(float(np.percentile(ia, 95)), 2),
                        "Bps": round(sum(p[1] for p in pk) / a.windows, 0)}
            summary["windows"].append({"t_start_utc": dt.datetime.fromtimestamp(w0, dt.timezone.utc).isoformat(),
                                       "down": quick(dn), "up": quick(up)})
            w0 += a.windows
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary[k] for k in ("server_flow", "down", "up")}, indent=2))
    print("\nOther flows ->", os.path.join(a.out, "flows.csv"))
    print("NOTE: rates are *send* rates (R2/R4). They bound but do not equal the server sim tick (R1).")


if __name__ == "__main__":
    main()
