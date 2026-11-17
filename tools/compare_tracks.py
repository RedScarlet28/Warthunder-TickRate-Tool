#!/usr/bin/env python3
"""
Experiment C: compare where PC-A *is* (A's own client) with where PC-B *sees* A.

Inputs: two telemetry JSONL files from tools/telemetry_logger.py (clocks NTP-synced).
  A file: A's own position = map_obj object with icon == "Player".
  B file: A's position as seen by B = the target aircraft object in B's map_obj
          (default: the only non-Player aircraft; use --target-color to disambiguate).

Outputs (in --out):
  tracks.csv            per-B-sample: t, A_true xy, B_view xy, error m, along/cross-track error, A g-load, TAS
  update_intervals.png  staircase analysis: how often B's view of A changes (per-object update rate R3),
                        and how often A's own icon changes (API calibration, C0)
  error_vs_time.png     error magnitude + A g-load over time
  error_vs_g.png        error vs lateral load factor (H4: e ~ 1/2 a tau^2)
  summary.json          R3 stats, error percentiles, best-fit display delay, fitted tau

Usage:
  python -I tools/compare_tracks.py --a data/s1/pcA/telemetry/x.jsonl --b data/s1/pcB/telemetry/y.jsonl \
        --out analysis/s1/expC --t0 2026-11-14T19:03:00 --t1 2026-11-14T19:08:00
  --clock-offset-ms  add to B timestamps (from the flash-video cross-check; B_true = B + offset)
"""
import argparse, datetime as dt, json, os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

G = 9.80665


def load(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def map_scale(recs):
    for r in recs:
        if r.get("ep") == "map_info" and isinstance(r.get("data"), dict) and "map_min" in r["data"]:
            d = r["data"]
            return np.array(d["map_min"], float), np.array(d["map_max"], float)
    raise SystemExit("no map_info in log (needs to be in battle while logging)")


def to_m(x, y, mn, mx):
    return mn[0] + x * (mx[0] - mn[0]), mn[1] + y * (mx[1] - mn[1])


def series(recs, pick):
    t, xy = [], []
    for r in recs:
        if r.get("ep") != "map_obj" or not isinstance(r.get("data"), list):
            continue
        o = pick(r["data"])
        if o is not None and "x" in o:
            t.append(r["t_wall_ns"] / 1e9); xy.append((o["x"], o["y"]))
    return np.array(t), np.array(xy, float)


def state_series(recs, key):
    t, v = [], []
    for r in recs:
        if r.get("ep") == "state" and isinstance(r.get("data"), dict) and key in r["data"]:
            t.append(r["t_wall_ns"] / 1e9); v.append(float(r["data"][key]))
    return np.array(t), np.array(v)


def change_intervals(t, xy, eps=1e-9, k=6.0, min_jump_m=0.05, simple=False):
    """Find instants where a NEW network update for this object was applied.

    Two regimes:
      * held positions (object frozen between updates): an update = any position change.
      * extrapolated positions (object moves every frame along a straight line between
        updates): an update = a kink, i.e. a large residual against a linear prediction
        from the previous two samples.
    xy must be in metres for the kink threshold to be meaningful.
    """
    if len(t) < 4:
        return np.array([]), np.array([])
    ch = np.concatenate([[True], np.any(np.abs(np.diff(xy, axis=0)) > eps, axis=1)])
    if simple or ch.mean() < 0.8:
        tc = t[ch]
        return tc, np.diff(tc) * 1000
    # keep only changed samples (drops duplicate polls), then linear-prediction residuals
    tt, xx = t[ch], xy[ch]
    dt1 = np.diff(tt)[1:]; dt0 = np.diff(tt)[:-1]
    ratio = np.divide(dt1, dt0, out=np.ones_like(dt1), where=dt0 > 0)[:, None]
    pred = xx[1:-1] + (xx[1:-1] - xx[:-2]) * ratio
    resid = np.hypot(*(xx[2:] - pred).T)
    thr = max(k * np.median(resid), min_jump_m)
    idx = np.where(resid > thr)[0] + 2
    if len(idx) == 0:
        return np.array([]), np.array([])
    # a jump at sample i also corrupts the prediction for i+1 -> refractory of ~2.5 sample spacings
    refr = 2.5 * np.median(np.diff(tt))
    tc_list = []
    for ti in tt[idx]:
        if not tc_list or ti - tc_list[-1] > refr:
            tc_list.append(ti)
    tc = np.array(tc_list)
    return tc, np.diff(tc) * 1000


def parse_time(s):
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return (d if d.tzinfo else d.astimezone()).timestamp()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True)
    ap.add_argument("--out", default="analysis/expC")
    ap.add_argument("--t0"); ap.add_argument("--t1")
    ap.add_argument("--target-color", help="hex color of A's icon in B's map_obj, e.g. '#fa0C00'")
    ap.add_argument("--clock-offset-ms", type=float, default=0.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0, t1 = parse_time(a.t0), parse_time(a.t1)

    ra = list(load(a.a)); rb = list(load(a.b))
    for r in rb:
        if "t_wall_ns" in r:
            r["t_wall_ns"] += int(a.clock_offset_ms * 1e6)
    mn, mx = map_scale(ra)

    own = lambda objs: next((o for o in objs if o.get("icon") == "Player"), None)

    def target(objs):
        c = [o for o in objs if o.get("type") == "aircraft" and o.get("icon") != "Player"]
        if a.target_color:
            c = [o for o in c if str(o.get("color", "")).lower() == a.target_color.lower()]
        return c[0] if len(c) == 1 else None

    ta, xa = series(ra, own)        # truth (A self)
    tb, xb = series(rb, target)     # B's view of A
    tbo, xbo = series(rb, own)      # B's own position (for distance)
    if t0 or t1:
        def win(t, x):
            m = np.ones(len(t), bool)
            if t0: m &= t >= t0
            if t1: m &= t <= t1
            return t[m], x[m]
        ta, xa = win(ta, xa); tb, xb = win(tb, xb); tbo, xbo = win(tbo, xbo)
    if len(ta) < 10 or len(tb) < 10:
        raise SystemExit(f"not enough samples: A={len(ta)} B={len(tb)}")

    XA = np.column_stack(to_m(xa[:, 0], xa[:, 1], mn, mx))
    XB = np.column_stack(to_m(xb[:, 0], xb[:, 1], mn, mx))
    XBO = np.column_stack(to_m(xbo[:, 0], xbo[:, 1], mn, mx)) if len(tbo) else None

    # --- staircase / update-rate analysis (positions in metres) ---
    tca, iva = change_intervals(ta, XA, simple=True)   # API refresh calibration: raw change cadence
    tcb, ivb = change_intervals(tb, XB)

    # --- error evaluated at every distinct B sample (duplicate polls removed) ---
    keepb = np.concatenate([[True], np.any(np.abs(np.diff(xb, axis=0)) > 1e-12, axis=1)])
    tb_c = tb[keepb]
    XB_c = np.column_stack([np.interp(tb_c, tb, XB[:, 0]), np.interp(tb_c, tb, XB[:, 1])])
    XA_at = np.column_stack([np.interp(tb_c, ta, XA[:, 0]), np.interp(tb_c, ta, XA[:, 1])])
    err = XB_c - XA_at
    emag = np.hypot(err[:, 0], err[:, 1])
    # A velocity for along/cross decomposition
    vA = np.gradient(XA, ta, axis=0)
    vA_at = np.column_stack([np.interp(tb_c, ta, vA[:, 0]), np.interp(tb_c, ta, vA[:, 1])])
    sp = np.hypot(vA_at[:, 0], vA_at[:, 1]) + 1e-9
    along = (err * vA_at).sum(1) / sp               # + = B shows A AHEAD (extrapolation overshoot)
    cross = (err[:, 0] * vA_at[:, 1] - err[:, 1] * vA_at[:, 0]) / sp

    # --- best-fit display delay: B(t) ~ A(t - L) ---
    lags = np.arange(-500, 1500, 2) / 1000
    cost = [np.nanmedian(np.hypot(np.interp(tb_c - L, ta, XA[:, 0]) - XB_c[:, 0],
                                  np.interp(tb_c - L, ta, XA[:, 1]) - XB_c[:, 1])) for L in lags]
    best_L = float(lags[int(np.argmin(cost))])

    # --- g-load / TAS from A's state ---
    tg, ny = state_series(ra, "Ny")
    tt, tas = state_series(ra, "TAS, km/h")
    g_at = np.interp(tb_c, tg, ny) if len(tg) else np.full(len(tb_c), np.nan)
    tas_at = np.interp(tb_c, tt, tas) if len(tt) else np.full(len(tb_c), np.nan)
    dist = (np.hypot(*(np.column_stack([np.interp(tb_c, tbo, XBO[:, 0]), np.interp(tb_c, tbo, XBO[:, 1])]) - XA_at).T)
            if XBO is not None else np.full(len(tb_c), np.nan))

    # Fit e ~ 1/2 * a_lat * tau^2  with a_lat = sqrt(max(Ny^2-1,0))*g (level-turn approximation)
    alat = np.sqrt(np.clip(g_at ** 2 - 1, 0, None)) * G
    m = np.isfinite(alat) & (alat > 2 * G)
    tau = float(np.sqrt(2 * np.median(np.abs(cross[m]) / alat[m]))) if m.sum() > 20 else None

    with open(os.path.join(a.out, "tracks.csv"), "w") as f:
        f.write("t_utc,Ax,Ay,Bx,By,err_m,along_m,cross_m,A_g,A_tas_kmh,dist_m\n")
        for i in range(len(tb_c)):
            f.write(f"{tb_c[i]:.6f},{XA_at[i,0]:.2f},{XA_at[i,1]:.2f},{XB_c[i,0]:.2f},{XB_c[i,1]:.2f},"
                    f"{emag[i]:.2f},{along[i]:.2f},{cross[i]:.2f},{g_at[i]:.2f},{tas_at[i]:.1f},{dist[i]:.0f}\n")

    pct = lambda x: {k: round(float(np.nanpercentile(x, q)), 3) for k, q in (("p5", 5), ("p50", 50), ("p95", 95), ("p99", 99))} if len(x) else None
    summary = {
        "samples_A": len(ta), "samples_B": len(tb),
        "A_own_icon_update_interval_ms": pct(iva),
        "B_view_of_A_update_interval_ms (R3)": pct(ivb),
        "R3_hz_from_median": round(1000 / np.median(ivb), 2) if len(ivb) else None,
        "error_m": pct(emag), "along_track_m (+ahead)": pct(along), "cross_track_m": pct(cross),
        "best_fit_display_delay_ms": round(best_L * 1000, 1),
        "fitted_extrapolation_horizon_tau_ms": round(tau * 1000, 1) if tau else None,
        "map_min": mn.tolist(), "map_max": mx.tolist(),
        "caveat": "map_obj precision/refresh must be validated first (A_own_icon_update_interval_ms)."
    }
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
    ax[0].hist(iva[iva < 300], bins=150, alpha=.6, label="A own icon (API calib.)")
    ax[0].hist(ivb[ivb < 300], bins=150, alpha=.6, label="B's view of A (R3)")
    for hz in (10, 15, 20, 30, 48, 60):
        ax[0].axvline(1000 / hz, ls="--", lw=.6, color="k"); ax[0].text(1000 / hz, ax[0].get_ylim()[1] * .9, f"{hz}", fontsize=7)
    ax[0].set_xlabel("ms between position changes"); ax[0].legend()
    if np.isfinite(dist).any():
        d_at_upd = np.interp(tcb[1:], tb_c, dist) if len(tcb) > 1 else np.array([])
        ax[1].scatter(d_at_upd, ivb, s=3); ax[1].set_xlabel("A–B distance (m)"); ax[1].set_ylabel("update interval ms")
        ax[1].set_ylim(0, 400); ax[1].set_title("R3 vs distance (H3)")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "update_intervals.png"), dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.plot(tb_c - tb_c[0], emag, lw=.7, label="|error| m"); ax.plot(tb_c - tb_c[0], along, lw=.5, label="along-track (+ahead)")
    ax2 = ax.twinx(); ax2.plot(tb_c - tb_c[0], g_at, color="r", lw=.5, alpha=.6); ax2.set_ylabel("A g-load", color="r")
    ax.set_xlabel("s"); ax.legend(loc="upper left"); fig.tight_layout()
    fig.savefig(os.path.join(a.out, "error_vs_time.png"), dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(g_at, emag, s=3, c=np.nan_to_num(tas_at), cmap="viridis")
    ax.axhline(12, ls=":", color="k"); ax.text(1, 12.5, "≈ fighter wingspan", fontsize=8)
    ax.set_xlabel("A load factor (g)"); ax.set_ylabel("position error seen by B (m)"); ax.set_title("H4: error vs manoeuvre")
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "error_vs_g.png"), dpi=110); plt.close(fig)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
