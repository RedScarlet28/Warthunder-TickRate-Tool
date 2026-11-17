#!/usr/bin/env python3
"""
Clock pairing between two PCs (NTP-style, but continuous and logged).

  Salty's PC = REFERENCE clock:   python clock_sync.py serve
  Other PC   = CLIENT:            python clock_sync.py client --ref <Salty's IP> --out <dir>

The client sends a UDP probe 20x per second. Each exchange gives four timestamps
(t1 client send, t2 ref receive, t3 ref reply, t4 client receive), all from the precise
Windows wall clock (GetSystemTimePreciseAsFileTime, µs resolution):

    offset = ((t2 - t1) + (t3 - t4)) / 2      ->  ref_time = client_time + offset
    delay  = (t4 - t1) - (t3 - t2)             (network round trip)

Exchanges with the smallest round trip are the most accurate. On a wired LAN, expect
an offset uncertainty of ~0.05–0.3 ms. Every exchange is logged, so the analyzer can follow
drift or a time-service step during the session.

Firewall: the first `serve` run on Salty's PC triggers a Windows Firewall prompt.
Allow it on *Private* networks (UDP port 47123).
"""
import argparse, json, os, socket, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
from telemetry_logger import wall_ns  # noqa: E402  (precise wall clock)

PORT = 47123
FMT_REQ = "<4sQq"        # magic, seq, t1
FMT_REP = "<4sQqqq"      # magic, seq, t1, t2, t3
MAGIC = b"WTCS"


def serve(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    print(f"[reference clock] serving on UDP {port} - leave this running. Ctrl+C to stop.")
    n = 0
    try:
        while True:
            data, addr = s.recvfrom(64)
            t2 = wall_ns()
            if len(data) != struct.calcsize(FMT_REQ):
                continue
            magic, seq, t1 = struct.unpack(FMT_REQ, data)
            if magic != MAGIC:
                continue
            t3 = wall_ns()
            s.sendto(struct.pack(FMT_REP, MAGIC, seq, t1, t2, t3), addr)
            n += 1
            if n % 1200 == 0:
                print(f"  {time.strftime('%H:%M:%S')} answered {n} probes (last from {addr[0]})")
    except KeyboardInterrupt:
        pass


def client(ref, port, out, hz):
    os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f"clock_{socket.gethostname()}_vs_{ref.replace('.', '-')}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    f = open(fn, "a", encoding="utf-8", buffering=1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.2)
    f.write(json.dumps({"ep": "_meta", "ref": ref, "host": socket.gethostname(), "hz": hz,
                        "formula": "ref_time = local_time + offset_ns"}) + "\n")
    print(f"[client] pairing with reference {ref}:{port} at {hz} Hz -> {fn}")
    seq = 0; window = []; last_print = time.monotonic()
    period = 1.0 / hz
    stop_file = os.path.join(out, "STOP")
    try:
        while not (seq % 20 == 0 and os.path.exists(stop_file)):
            seq += 1
            t1 = wall_ns()
            s.sendto(struct.pack(FMT_REQ, MAGIC, seq, t1), (ref, port))
            try:
                while True:
                    data, _ = s.recvfrom(64)
                    t4 = wall_ns()
                    magic, rseq, rt1, t2, t3 = struct.unpack(FMT_REP, data)
                    if magic == MAGIC and rseq == seq:
                        break
                off = ((t2 - t1) + (t3 - t4)) // 2
                dly = (t4 - t1) - (t3 - t2)
                f.write(json.dumps({"t_local_ns": t1, "seq": seq, "offset_ns": off, "delay_ns": dly}) + "\n")
                window.append((dly, off))
            except socket.timeout:
                f.write(json.dumps({"t_local_ns": t1, "seq": seq, "timeout": True}) + "\n")
            if time.monotonic() - last_print > 5 and window:
                window.sort()
                best = window[: max(1, len(window) // 10)]
                off_ms = sum(o for _, o in best) / len(best) / 1e6
                print(f"  {time.strftime('%H:%M:%S')}  offset {off_ms:+.3f} ms   min RTT {window[0][0] / 1e6:.3f} ms   ({len(window)} probes)")
                window = []; last_print = time.monotonic()
            time.sleep(max(0.0, period - (wall_ns() - t1) / 1e9))
    except KeyboardInterrupt:
        pass
    f.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    sv = sub.add_parser("serve"); sv.add_argument("--port", type=int, default=PORT)
    cl = sub.add_parser("client")
    cl.add_argument("--ref", required=True, help="IP of Salty's PC (reference)")
    cl.add_argument("--port", type=int, default=PORT)
    cl.add_argument("--out", default="clock_out")
    cl.add_argument("--hz", type=float, default=20.0)
    a = ap.parse_args()
    if a.mode == "serve":
        serve(a.port)
    else:
        client(a.ref, a.port, a.out, a.hz)


if __name__ == "__main__":
    main()
