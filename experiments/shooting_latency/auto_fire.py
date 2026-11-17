#!/usr/bin/env python3
"""
Auto-fire for the shooting-latency test: presses a key (or the left mouse button) at RANDOM intervals
and logs the exact moment of every press, in the same format as input_logger.py.

!! Only for PRIVATE custom battles with just your own accounts. This injects input into the game:
!! that is what macros do, and Gaijin's rules on macros apply. Use it at your own risk, never in
!! public matches.

Why random and not "every 1.5 s": the analysis needs presses that land at random points within the
tick cycle. 1.5 s is exactly 36 cycles of a 24 Hz tick, so a fixed 1.5 s rhythm would hit the SAME
point of the cycle every time and the measurement would see no tick at all. Default: uniform 1.0-2.0 s
(mean 1.5 s), plus sub-millisecond random jitter.

Controls (global hotkeys, work while the game has focus):
  Ctrl+Shift+F8   start / pause firing      (high beep = firing, low beep = paused)
  Ctrl+Shift+F9   quit
Safety: it only presses while the War Thunder window is in the foreground (pauses by itself if you
alt-tab or open chat in another window), and stops after --max presses (3 beeps).

Usage:
  python auto_fire.py --out <dir> --key k          # bind your machine gun to K in War Thunder
  python auto_fire.py --out <dir> --mouse          # click the left mouse button instead (no binding needed)
  python auto_fire.py --test                       # 5 harmless F24 presses (no game needed)
Then analyse with:  analyze_shooting.py --shooter-inputs <dir>/inputs_autofire_*.jsonl --fire-button autofire
"""
import argparse, ctypes, json, os, random, socket, sys, threading, time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
from telemetry_logger import wall_ns  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")
winmm = ctypes.WinDLL("winmm")

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000
VK_F8, VK_F9, WM_HOTKEY, WM_TIMER = 0x77, 0x78, 0x0312, 0x0113

VK = {"space": 0x20, "enter": 0x0D, "tab": 0x09}
VK.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})


def make_sender(key, mouse):
    if mouse:
        def send(down):
            i = INPUT(type=INPUT_MOUSE)
            i.u.mi.dwFlags = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
            user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
        return send
    vk = VK.get(key.lower())
    if vk is None:
        sys.exit(f"unknown key '{key}'. Use a-z, 0-9, f1-f24, space")
    scan = user32.MapVirtualKeyW(vk, 0)       # games read scan codes (DirectInput/raw input)

    def send(down):
        i = INPUT(type=INPUT_KEYBOARD)
        i.u.ki.wVk = 0; i.u.ki.wScan = scan
        i.u.ki.dwFlags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
    return send


def foreground_title():
    h = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    return buf.value


def beep(freq, ms, n=1):
    def run():
        for _ in range(n):
            kernel32.Beep(freq, ms); time.sleep(0.05)
    threading.Thread(target=run, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "data", time.strftime("%Y%m%d"), os.environ.get("COMPUTERNAME", socket.gethostname())),
                    help="default: data/<today>/<this PC> (same folder as start_shooting.ps1)")
    ap.add_argument("--key", default="k", help="key to press (bind the gun to it in War Thunder)")
    ap.add_argument("--mouse", action="store_true", help="click the left mouse button instead of a key")
    ap.add_argument("--min", type=float, default=1.0, help="shortest gap between presses, s")
    ap.add_argument("--max-gap", type=float, default=2.0, help="longest gap between presses, s")
    ap.add_argument("--hold-ms", type=float, default=50, help="how long the key is held (short = 1 burst)")
    ap.add_argument("--max", type=int, default=300, help="stop after this many presses")
    ap.add_argument("--window", default="War Thunder", help="only press while the foreground window title contains this")
    ap.add_argument("--test", action="store_true", help="5 harmless F24 presses, no game, no hotkey")
    a = ap.parse_args()
    if a.max_gap <= a.min:
        sys.exit("--max-gap must be larger than --min")

    if a.test:   # harmless: F24 exists on no keyboard, nothing reacts to it
        a.key, a.mouse, a.max, a.min, a.max_gap = "f24", False, 5, 0.3, 0.6
    send = make_sender(a.key, a.mouse)
    btn_name = "autofire"
    os.makedirs(a.out, exist_ok=True)
    host = socket.gethostname().lower()
    path = os.path.join(a.out, f"inputs_autofire_{host}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    f = open(path, "w", encoding="utf-8")
    f.write(json.dumps({"ep": "_meta", "host": host, "keys": [btn_name], "source": "auto_fire.py",
                        "sent": "mouse_left" if a.mouse else a.key, "gap_s": [a.min, a.max_gap], "hold_ms": a.hold_ms,
                        "clock": "t_wall_ns = GetSystemTimePreciseAsFileTime; t_mono_ns = QPC; taken right before SendInput"}) + "\n")
    f.flush()
    winmm.timeBeginPeriod(1)

    state = {"on": a.test, "quit": False, "n": 0}
    window = None if a.test else a.window

    def press_once():
        t_wall = wall_ns(); t_mono = time.perf_counter_ns()
        send(True)
        f.write(json.dumps({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "btn": btn_name, "down": True, "injected": True}) + "\n")
        time.sleep(a.hold_ms / 1000)
        t_wall = wall_ns(); t_mono = time.perf_counter_ns()
        send(False)
        f.write(json.dumps({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "btn": btn_name, "down": False, "injected": True}) + "\n")
        f.flush()
        state["n"] += 1

    def fire_loop():
        last_skip_msg = 0
        while not state["quit"]:
            if not state["on"]:
                time.sleep(0.02); continue
            gap = random.uniform(a.min, a.max_gap)
            t_end = time.perf_counter() + gap
            while time.perf_counter() < t_end and state["on"] and not state["quit"]:
                time.sleep(0.005)
            if not state["on"] or state["quit"]:
                continue
            if window and window.lower() not in foreground_title().lower():
                if time.time() - last_skip_msg > 5:
                    print(f"  (paused: '{a.window}' is not the active window)"); last_skip_msg = time.time()
                continue
            press_once()
            print(f"\r  presses: {state['n']}/{a.max}   ", end="", flush=True)
            if state["n"] >= a.max:
                state["on"] = False; print("\n  reached --max, stopped."); beep(500, 150, 3)
                if a.test:
                    state["quit"] = True

    th = threading.Thread(target=fire_loop, daemon=True); th.start()

    if a.test:
        print("TEST: 5 harmless F24 presses ...")
        th.join()
    else:
        ok1 = user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F8)
        ok2 = user32.RegisterHotKey(None, 2, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F9)
        if not (ok1 and ok2):
            sys.exit("could not register Ctrl+Shift+F8/F9 (another program uses them?)")
        sent = "left mouse button" if a.mouse else f"key '{a.key.upper()}'"
        print(f"Auto-fire ready. Sends {sent} every {a.min}-{a.max_gap} s (random), held {a.hold_ms:.0f} ms, max {a.max} presses.")
        print(f"Only while '{a.window}' is the active window.")
        print("  Ctrl+Shift+F8 = start/pause    Ctrl+Shift+F9 = quit")
        print(f"Log: {path}")
        user32.SetTimer(None, 0, 1000, None)     # wake GetMessage every second so Ctrl+C works
        msg = wintypes.MSG()
        try:
            while not state["quit"] and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    if msg.wParam == 1:
                        state["on"] = not state["on"]
                        if state["on"] and state["n"] >= a.max:
                            state["n"] = 0
                        print(f"\n{'FIRING' if state['on'] else 'paused'}")
                        beep(1200 if state["on"] else 400, 120)
                    elif msg.wParam == 2:
                        state["quit"] = True
        except KeyboardInterrupt:
            pass
        state["quit"] = True
        user32.UnregisterHotKey(None, 1); user32.UnregisterHotKey(None, 2)
    th.join(timeout=3)
    winmm.timeEndPeriod(1)
    f.close()
    print(f"\n{state['n']} presses logged -> {path}")


if __name__ == "__main__":
    main()
