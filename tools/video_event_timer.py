#!/usr/bin/env python3
"""
Frame-accurate event timing from a screen recording or high-speed camera video.

Watches one or more regions of interest (ROIs) and reports the frames where each ROI
changes abruptly (onset of muzzle flash, hit spark, server hit-lines around the sight,
a sync-flash, a model "jump" ...).

Usage:
  # pick ROIs interactively on a frame (drag a box, ENTER; repeat; ESC to finish)
  python -I tools/video_event_timer.py rec.mp4 --pick --names muzzle,spark,hitlines --out analysis/expB
  # or give ROIs explicitly (x,y,w,h in pixels)
  python -I tools/video_event_timer.py rec.mp4 --roi hitlines=930,500,60,60 --roi spark=1000,420,80,80
Options:
  --fps-override 240     (phone slow-mo files often store 30 fps metadata; give the real capture fps)
  --k 6                  onset threshold in robust z-score (MAD) units
  --refractory-ms 40     ignore re-triggers inside this window
  --t-offset-s           add to video time to get wall clock (from the sync-flash frame)
Outputs: <name>_scores.csv (per-frame change score per ROI) and events.csv (onsets).
Pair events: e.g. delay = first 'hitlines' onset after each 'spark' onset.
"""
import argparse, csv, os, sys

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("pip install opencv-python")


def parse_roi(s):
    name, xywh = s.split("=")
    return name, tuple(int(v) for v in xywh.split(","))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("--out", default="analysis/video")
    ap.add_argument("--roi", action="append", default=[])
    ap.add_argument("--pick", action="store_true"); ap.add_argument("--names", default="")
    ap.add_argument("--fps-override", type=float, default=0)
    ap.add_argument("--k", type=float, default=6.0)
    ap.add_argument("--refractory-ms", type=float, default=40)
    ap.add_argument("--t-offset-s", type=float, default=0.0)
    ap.add_argument("--start-s", type=float, default=0); ap.add_argument("--end-s", type=float, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        sys.exit("cannot open video")
    fps = a.fps_override or cap.get(cv2.CAP_PROP_FPS)
    if a.start_s:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(a.start_s * (cap.get(cv2.CAP_PROP_FPS))))
    ok, frame = cap.read()
    if not ok:
        sys.exit("empty video")

    rois = dict(parse_roi(r) for r in a.roi)
    if a.pick:
        names = [n for n in a.names.split(",") if n] or [f"roi{i}" for i in range(8)]
        for n in names:
            r = cv2.selectROI(f"select ROI '{n}' (ENTER=ok, c=skip)", frame, showCrosshair=True)
            cv2.destroyAllWindows()
            if r[2] > 0 and r[3] > 0:
                rois[n] = tuple(int(v) for v in r)
                print(f"--roi {n}={','.join(map(str, rois[n]))}")
    if not rois:
        sys.exit("no ROIs")

    prev = {n: None for n in rois}
    scores = {n: [] for n in rois}
    idx = int(a.start_s * cap.get(cv2.CAP_PROP_FPS)) if a.start_s else 0
    frames = []
    while ok:
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for n, (x, y, w, h) in rois.items():
            patch = g[y:y + h, x:x + w].astype(np.int16)
            scores[n].append(0.0 if prev[n] is None else float(np.mean(np.abs(patch - prev[n]))))
            prev[n] = patch
        frames.append(idx)
        idx += 1
        if a.end_s and idx / (cap.get(cv2.CAP_PROP_FPS) or fps) > a.end_s:
            break
        ok, frame = cap.read()
    cap.release()

    frames = np.array(frames)
    t = frames / fps + a.t_offset_s
    events = []
    refr = int(a.refractory_ms / 1000 * fps) or 1
    for n, s in scores.items():
        s = np.array(s)
        med = np.median(s); mad = np.median(np.abs(s - med)) * 1.4826 + 1e-6
        z = (s - med) / mad
        last = -10 ** 9
        for i in np.where(z > a.k)[0]:
            if i - last > refr:
                events.append((n, int(frames[i]), float(t[i]), float(z[i])))
            last = i
        with open(os.path.join(a.out, f"{n}_scores.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["frame", "t_s", "score", "z"])
            for i in range(len(s)):
                w.writerow([int(frames[i]), f"{t[i]:.6f}", f"{s[i]:.3f}", f"{z[i]:.2f}"])
    events.sort(key=lambda e: e[1])
    with open(os.path.join(a.out, "events.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["roi", "frame", "t_s", "z"]); w.writerows(events)
    print(f"fps used: {fps}  frame quantum: {1000 / fps:.2f} ms  events: {len(events)}")
    for n in rois:
        print(f"  {n}: {sum(1 for e in events if e[0] == n)} onsets")


if __name__ == "__main__":
    main()
