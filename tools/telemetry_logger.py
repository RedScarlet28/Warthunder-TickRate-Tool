#!/usr/bin/env python3
"""
War Thunder localhost telemetry logger (official read-only API on 127.0.0.1:8111).

Polls the chosen endpoints at a fixed rate, one thread per endpoint, and writes
JSON Lines with precise timestamps:
    t_wall_ns : UTC wall clock (GetSystemTimePreciseAsFileTime on Windows) at request start (sync PCs with NTP!)
    t_mono_ns : monotonic clock (perf_counter_ns) at request start
    rtt_us    : HTTP request duration (local API latency, normally < 2 ms)
    ep        : endpoint name
    changed   : True if the payload differs from the previous poll (makes staircases easy to find)
    data      : parsed JSON payload

Stdlib only. Usage:
    python tools/telemetry_logger.py --out data/session_x/pcA/telemetry --hz 100
    python tools/telemetry_logger.py --selftest          # check the game API is reachable
Press Enter in the console to write a MARKER line (with an optional note), Ctrl+C to stop.
"""
import argparse, json, os, socket, sys, threading, time, urllib.request

def _make_precise_wall_ns():
    """time.time_ns() on Windows/Python<3.13 uses GetSystemTimeAsFileTime (15.6 ms steps!).
    Use GetSystemTimePreciseAsFileTime (sub-microsecond, still NTP-disciplined) when available."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            fn = ctypes.windll.kernel32.GetSystemTimePreciseAsFileTime
            fn.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
            ft = wintypes.FILETIME()
            EPOCH_DIFF_100NS = 116444736000000000  # 1601 -> 1970

            def precise_ns():
                fn(ctypes.byref(ft))
                return (((ft.dwHighDateTime << 32) | ft.dwLowDateTime) - EPOCH_DIFF_100NS) * 100
            precise_ns()
            return precise_ns
        except Exception:
            pass
    return time.time_ns


wall_ns = _make_precise_wall_ns()

BASE = "http://127.0.0.1:8111"
ENDPOINTS = {
    "state":      "/state",           # own aircraft: IAS/TAS, H, M, AoA, Ny (g), Vy, Wx ...
    "indicators": "/indicators",      # cockpit gauges, vehicle type
    "map_obj":    "/map_obj.json",    # all minimap objects, normalized x/y (0..1)
    "map_info":   "/map_info.json",   # map_min/map_max in metres -> convert normalized coords
    "hudmsg":     "/hudmsg?lastEvt=0&lastDmg=0",  # kill / damage feed (we dedupe by id)
}
DEFAULT_SET = ["state", "map_obj", "map_info", "hudmsg"]
SLOW = {"map_info": 1.0, "hudmsg": 10.0}  # max Hz for slowly-changing endpoints


def fetch(path, timeout=0.5):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.read()


class Writer:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8", buffering=1 << 16)
        self.lock = threading.Lock()

    def write(self, obj):
        line = json.dumps(obj, separators=(",", ":"))
        with self.lock:
            self.f.write(line + "\n")

    def flush(self):
        with self.lock:
            self.f.flush()

    def close(self):
        with self.lock:
            self.f.flush(); self.f.close()


def poll_loop(name, hz, writer, stop, stats):
    period_ns = int(1e9 / hz)
    next_t = time.perf_counter_ns()
    last_raw = None
    last_hud_evt = last_hud_dmg = 0
    while not stop.is_set():
        t_mono = time.perf_counter_ns(); t_wall = wall_ns()
        path = ENDPOINTS[name]
        if name == "hudmsg":
            path = f"/hudmsg?lastEvt={last_hud_evt}&lastDmg={last_hud_dmg}"
        try:
            raw = fetch(path)
            rtt = (time.perf_counter_ns() - t_mono) // 1000
            changed = raw != last_raw
            last_raw = raw
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw.decode("utf-8", "replace")
            if name == "hudmsg" and isinstance(data, dict):
                for k, attr in (("events", "evt"), ("damage", "dmg")):
                    for m in data.get(k, []) or []:
                        if attr == "evt":
                            last_hud_evt = max(last_hud_evt, m.get("id", 0))
                        else:
                            last_hud_dmg = max(last_hud_dmg, m.get("id", 0))
                changed = bool(data.get("events") or data.get("damage"))
            if changed or name not in ("hudmsg",):
                writer.write({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "rtt_us": rtt,
                              "ep": name, "changed": changed, "data": data})
            stats[name]["ok"] += 1
            stats[name]["changed"] += int(changed)
        except Exception as e:  # game not running / API not ready
            stats[name]["err"] += 1
            if stats[name]["err"] % 200 == 1:
                writer.write({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "ep": name,
                              "error": repr(e)})
        next_t += period_ns
        sleep_ns = next_t - time.perf_counter_ns()
        if sleep_ns > 0:
            time.sleep(sleep_ns / 1e9)
        else:
            next_t = time.perf_counter_ns()  # fell behind; resync, don't burst


def selftest():
    ok = True
    for name, path in ENDPOINTS.items():
        try:
            t0 = time.perf_counter()
            raw = fetch(path, timeout=1.0)
            dt = (time.perf_counter() - t0) * 1000
            print(f"[OK ] {name:10s} {len(raw):6d} B  {dt:5.1f} ms  {raw[:90]!r}")
        except Exception as e:
            ok = False
            print(f"[ERR] {name:10s} {e!r}")
    if not ok:
        print("\nStart War Thunder (the API answers from the hangar, full data in battle).")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="telemetry_out", help="output directory")
    ap.add_argument("--hz", type=float, default=100.0, help="poll rate for fast endpoints")
    ap.add_argument("--endpoints", default=",".join(DEFAULT_SET),
                    help="comma list from: " + ",".join(ENDPOINTS))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--status-sec", type=float, default=0,
                    help="print poll stats every N s (0 = silent; markers: use mark_hotkeys.py)")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())

    os.makedirs(a.out, exist_ok=True)
    host = socket.gethostname()
    fn = os.path.join(a.out, f"telemetry_{host}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    w = Writer(fn)
    w.write({"t_wall_ns": wall_ns(), "t_mono_ns": time.perf_counter_ns(), "ep": "_meta",
             "data": {"host": host, "hz": a.hz, "endpoints": a.endpoints, "python": sys.version}})
    stop = threading.Event()
    names = [n.strip() for n in a.endpoints.split(",") if n.strip()]
    stats = {n: {"ok": 0, "err": 0, "changed": 0} for n in names}
    threads = []
    for n in names:
        hz = min(a.hz, SLOW.get(n, a.hz))
        t = threading.Thread(target=poll_loop, args=(n, hz, w, stop, stats), daemon=True)
        t.start(); threads.append(t)
    print(f"Logging {names} at {a.hz} Hz -> {fn}\nCtrl+C = stop. (Markers: run mark_hotkeys.py in another tab.)")

    def marker_input():
        while not stop.is_set():
            try:
                note = input()
            except EOFError:
                return
            w.write({"t_wall_ns": wall_ns(), "t_mono_ns": time.perf_counter_ns(),
                     "ep": "_marker", "data": note})
            print(f"  marker @ {time.strftime('%H:%M:%S')} {note!r}")
    threading.Thread(target=marker_input, daemon=True).start()

    try:
        last_status = time.monotonic()
        while True:
            time.sleep(2)
            # heartbeat + flush: file keeps growing even with the game closed (health check relies on it)
            w.write({"t_wall_ns": wall_ns(), "t_mono_ns": time.perf_counter_ns(), "ep": "_hb",
                     "data": {n: dict(s) for n, s in stats.items()}})
            w.flush()
            if a.status_sec > 0 and time.monotonic() - last_status >= a.status_sec:
                last_status = time.monotonic()
                print("  " + "  ".join(f"{n}:{s['ok']}ok/{s['changed']}chg/{s['err']}err" for n, s in stats.items()))
    except KeyboardInterrupt:
        pass
    stop.set()
    for t in threads:
        t.join(timeout=1)
    w.close()
    print("saved", fn)


if __name__ == "__main__":
    main()
