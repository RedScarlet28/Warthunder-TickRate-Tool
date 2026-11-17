#!/usr/bin/env python3
"""
Passive input logger (Windows Raw Input, background sink). It only READS button events,
like stream input overlays do. It injects nothing and touches no game process.

Logs press/release of mouse buttons (always) and of any keys you whitelist
(e.g. your fire key if it is on the keyboard), with µs-precise wall-clock and QPC timestamps.
It deliberately does NOT log other keys, so chat and passwords are never recorded.

Usage:
  python input_logger.py --out <dir>                       # mouse buttons only
  python input_logger.py --out <dir> --keys space,lctrl    # + whitelisted keys
  python input_logger.py --selftest                        # sends a harmless F24 press to itself
Key names: a-z, 0-9, space, lctrl, rctrl, lshift, rshift, lalt, ralt, enter, f1-f24, or vk:0xNN.
"""
import argparse, ctypes, json, os, socket, sys, threading, time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
from telemetry_logger import wall_ns  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT, WM_DESTROY = 0x00FF, 0x0002
RID_INPUT, RIM_TYPEMOUSE, RIM_TYPEKEYBOARD = 0x10000003, 0, 1
RIDEV_INPUTSINK = 0x00000100
HWND_MESSAGE = wintypes.HWND(-3)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

MOUSE_FLAGS = {  # usButtonFlags bit -> (button, down)
    0x0001: ("mouse_left", True), 0x0002: ("mouse_left", False),
    0x0004: ("mouse_right", True), 0x0008: ("mouse_right", False),
    0x0010: ("mouse_middle", True), 0x0020: ("mouse_middle", False),
    0x0040: ("mouse_x1", True), 0x0080: ("mouse_x1", False),
    0x0100: ("mouse_x2", True), 0x0200: ("mouse_x2", False),
}
VK = {"space": 0x20, "enter": 0x0D, "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
      "lalt": 0xA4, "ralt": 0xA5, "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "tab": 0x09}
VK.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT), ("_pad", wintypes.USHORT),
                ("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT),
                ("ulRawButtons", wintypes.ULONG), ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT), ("Reserved", wintypes.USHORT),
                ("VKey", wintypes.USHORT), ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]


class _U(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", _U)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]


def parse_keys(s):
    out = {}
    for k in filter(None, (x.strip().lower() for x in s.split(","))):
        vk = int(k[3:], 16) if k.startswith("vk:") else VK.get(k)
        if vk is None:
            sys.exit(f"unknown key name: {k}")
        out[vk] = k
    return out


def run(out, keys, selftest=False):
    os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f"inputs_{socket.gethostname()}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    f = open(fn, "a", encoding="utf-8", buffering=1)
    f.write(json.dumps({"ep": "_meta", "host": socket.gethostname(), "keys": list(keys.values()),
                        "clock": "t_wall_ns = GetSystemTimePreciseAsFileTime; t_mono_ns = QPC"}) + "\n")
    held = set()
    counts = {"events": 0}
    buf = ctypes.create_string_buffer(256)
    hdr_size = ctypes.sizeof(RAWINPUTHEADER)

    def emit(name, down, injected):
        t_wall = wall_ns(); t_mono = time.perf_counter_ns()
        if down and name in held:
            return  # key auto-repeat
        (held.add if down else held.discard)(name)
        f.write(json.dumps({"t_wall_ns": t_wall, "t_mono_ns": t_mono, "btn": name,
                            "down": down, "injected": injected}) + "\n")
        counts["events"] += 1
        if not selftest:
            print(f"  {time.strftime('%H:%M:%S')}  {name:12s} {'DOWN' if down else 'up'}")

    stop_file = os.path.join(out, "STOP")

    @WNDPROC
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == 0x0113:  # WM_TIMER: graceful stop requested by stop_shooting.ps1
            if os.path.exists(stop_file):
                user32.PostQuitMessage(0)
            return 0
        if msg == WM_INPUT:
            size = wintypes.UINT(ctypes.sizeof(buf))
            if user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size), hdr_size) > 0:
                ri = RAWINPUT.from_buffer_copy(buf.raw[:ctypes.sizeof(RAWINPUT)])
                injected = not bool(ri.header.hDevice)
                if ri.header.dwType == RIM_TYPEMOUSE:
                    bf = ri.data.mouse.usButtonFlags
                    for bit, (name, down) in MOUSE_FLAGS.items():
                        if bf & bit:
                            emit(name, down, injected)
                elif ri.header.dwType == RIM_TYPEKEYBOARD:
                    vk = ri.data.keyboard.VKey
                    if vk in keys:
                        emit(keys[vk], not (ri.data.keyboard.Flags & 1), injected)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW(lpfnWndProc=wndproc, hInstance=hinst, lpszClassName="WTInputLogger")
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, "WTInputLogger", "WTInputLogger", 0, 0, 0, 0, 0,
                                  HWND_MESSAGE, None, hinst, None)
    devs = (RAWINPUTDEVICE * 2)(RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd),   # mouse
                                RAWINPUTDEVICE(1, 6, RIDEV_INPUTSINK, hwnd))   # keyboard
    if not user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        sys.exit(f"RegisterRawInputDevices failed: {ctypes.get_last_error()}")

    if selftest:
        def press():
            time.sleep(0.3)
            KEYEVENTF_KEYUP = 2
            user32.keybd_event(0x87, 0, 0, 0); time.sleep(0.05)   # F24 down/up (unused key)
            user32.keybd_event(0x87, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3); user32.PostMessageW(hwnd, 0x0012, 0, 0)  # WM_QUIT
        threading.Thread(target=press, daemon=True).start()
    else:
        print(f"Logging inputs (mouse buttons{', ' + ', '.join(keys.values()) if keys else ''}) -> {fn}")
        print("Ctrl+C to stop.")
        # timer keeps the loop waking so Ctrl+C works
        user32.SetTimer(hwnd, 1, 500, None)

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    f.close()
    return fn, counts["events"]


def main():
    if sys.platform != "win32":
        sys.exit("Windows only")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="inputs_out")
    ap.add_argument("--keys", default="", help="comma list of extra keys to log (e.g. your keyboard fire key)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        import tempfile
        fn, n = run(tempfile.mkdtemp(), {0x87: "f24"}, selftest=True)
        print(f"selftest: {n} events captured ({'OK' if n == 2 else 'FAIL'}) -> {fn}")
        sys.exit(0 if n == 2 else 1)
    run(a.out, parse_keys(a.keys))


if __name__ == "__main__":
    main()
