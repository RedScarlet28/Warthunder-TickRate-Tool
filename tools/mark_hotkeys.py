#!/usr/bin/env python3
"""
Global hotkey markers (Windows) - press while in game, no alt-tab needed.

Ctrl+Shift+<key> writes a timestamped marker line (µs-precise wall clock, same clock as
telemetry_logger.py) and beeps so you know it registered. The marker table below matches
PLAN.md Exp. A; edit it for other experiments, or pass --labels "1=foo,2=bar".

Usage:
    python tools/mark_hotkeys.py --out data/session_x/pcA/telemetry
"""
import argparse, ctypes, json, os, socket, sys, time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telemetry_logger import wall_ns  # noqa: E402

LABELS = {
    "1": "A1 hangar",
    "2": "A2 loading",
    "3": "A3 test flight",
    "4": "A4 alone",
    "5": "A4b look enemies",
    "6": "A4b look away",
    "7": "A5 furball",
    "8": "A6 ground",
    "9": "A8 custom 2 players",
    "0": "END",
    "M": "EVENT (something odd happened)",
}
MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312


def main():
    if sys.platform != "win32":
        sys.exit("Windows only")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="markers_out")
    ap.add_argument("--labels", default="", help='override, e.g. "1=C1 straight,2=C3 reversals"')
    ap.add_argument("--watch-pcap", default="", help="dir whose newest *.pcapng must keep growing")
    ap.add_argument("--watch-telemetry", default="", help="dir whose newest telemetry_*.jsonl must keep growing")
    ap.add_argument("--stale-sec", type=float, default=15.0)
    a = ap.parse_args()
    labels = dict(LABELS)
    for kv in filter(None, a.labels.split(",")):
        k, v = kv.split("=", 1); labels[k.strip().upper()] = v.strip()

    os.makedirs(a.out, exist_ok=True)
    fn = os.path.join(a.out, f"markers_{socket.gethostname()}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    f = open(fn, "a", encoding="utf-8", buffering=1)

    user32 = ctypes.windll.user32
    import winsound
    ids = {}
    for i, key in enumerate(labels, start=1):
        vk = ord(key)
        if not user32.RegisterHotKey(None, i, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, vk):
            print(f"  ! could not register Ctrl+Shift+{key} (in use by another app)")
            continue
        ids[i] = key
    print(f"Markers -> {fn}")
    for i, key in ids.items():
        print(f"  Ctrl+Shift+{key}  =  {labels[key]}")
    print("Leave this window open (can be in background). Ctrl+C or close to stop.")

    # ---- health check: are the recorders still writing? ----
    import glob

    def newest(d, pat):
        fs = glob.glob(os.path.join(d, pat))
        return max(fs, key=os.path.getmtime) if fs else None

    def health():
        """Return list of problems (empty = healthy)."""
        probs = []
        now = time.time()
        for d, pat, name in ((a.watch_pcap, "*.pcapng", "PACKET CAPTURE"),
                             (a.watch_telemetry, "telemetry_*.jsonl", "TELEMETRY LOGGER")):
            if not d:
                continue
            fn_ = newest(d, pat)
            if not fn_:
                probs.append(f"{name}: no file yet")
            elif now - os.path.getmtime(fn_) > a.stale_sec:
                probs.append(f"{name}: not written for {now - os.path.getmtime(fn_):.0f}s")
        return probs

    def warn(probs):
        print("  !!! WARNING - RECORDING PROBLEM: " + "; ".join(probs))
        f.write(json.dumps({"t_wall_ns": wall_ns(), "ep": "_health", "data": probs}) + "\n")
        for _ in range(3):
            winsound.Beep(300, 250); time.sleep(0.08)

    WM_TIMER = 0x0113
    # 1 s timer: keeps the message loop waking up (so Ctrl+C works) and drives the 15 s health check
    watching = bool(a.watch_pcap or a.watch_telemetry)
    user32.SetTimer(None, 0, 1000, None)
    if watching:
        print(f"Health check every 15 s (stale > {a.stale_sec:.0f}s => three low beeps).")
    last_warn = 0.0
    ticks = 0

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_TIMER:
                ticks += 1
                if not watching or ticks % 15:
                    continue
                probs = health()
                # the pcap file legitimately stalls when no UDP traffic (game closed) -> warn at most every 60 s
                if probs and time.time() - last_warn > 60:
                    warn(probs); last_warn = time.time()
            elif msg.message == WM_HOTKEY and msg.wParam in ids:
                t_wall = wall_ns(); t_mono = time.perf_counter_ns()
                key = ids[msg.wParam]
                probs = health()
                f.write(json.dumps({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "ep": "_marker",
                                    "key": key, "data": labels[key], "health": probs}) + "\n")
                print(f"  {time.strftime('%H:%M:%S')}  [{key}] {labels[key]}")
                if probs:
                    warn(probs)
                else:
                    winsound.Beep(1200 if key != "0" else 600, 120)
    except KeyboardInterrupt:
        pass
    finally:
        for i in ids:
            user32.UnregisterHotKey(None, i)
        f.close()


if __name__ == "__main__":
    main()
