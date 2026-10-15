"""
Pure analysis helpers for the CARLA plant check (no CARLA import, unit-tested).

The emulator's braking plant is closed-form: speed is held until the brake takes effect, brake force then ramps
linearly to a constant deceleration. CARLA is a physics engine with its own tyre and brake model, so the check is:
  1. fit CARLA's braking response with the same two-parameter shape (deceleration, ramp) from a braking test
  2. find CARLA's point of no return for a scenario by bisection on the brake latency
  3. compare it with the closed-form point of no return, using the assumed and the fitted parameters
"""
import math

import numpy as np

from sdv.plant.longitudinal import braking_distance, latest_safe_latency_s


def model_speed(t, v0, decel, ramp_s):
    """Speed t seconds after brake onset for the ramp-then-constant model."""
    t = np.asarray(t, dtype=float)
    if ramp_s <= 0:
        return np.maximum(0.0, v0 - decel * t)
    in_ramp = v0 - decel * t * t / (2 * ramp_s)
    after = v0 - decel * ramp_s / 2 - decel * (t - ramp_s)
    return np.maximum(0.0, np.where(t <= ramp_s, in_ramp, after))


def fit_braking(t, v, ramp_grid=None):
    """Least-squares (decel, ramp_s) for a speed trace recorded from brake onset (t=0 at onset)."""
    t, v = np.asarray(t, dtype=float), np.asarray(v, dtype=float)
    v0 = float(v[0])
    moving = v > 0.2 * v0                      # ignore the tail where the vehicle has (nearly) stopped
    t, v = t[moving], v[moving]
    best = None
    for ramp in (np.linspace(0.0, 0.4, 81) if ramp_grid is None else ramp_grid):
        basis = v0 - model_speed(t, v0, 1.0, ramp)          # speed lost per unit of deceleration
        denom = float(basis @ basis)
        if denom <= 0:
            continue
        decel = float(basis @ (v0 - v)) / denom
        err = float(np.sum((v0 - decel * basis - v) ** 2))
        if best is None or err < best[0]:
            best = (err, decel, float(ramp))
    return {"decel": best[1], "ramp_s": best[2], "rmse": math.sqrt(best[0] / len(t))}


def closed_form_ponr_ms(v0_ms, d0_m, decel, ramp_s):
    return 1000.0 * latest_safe_latency_s(v0_ms, d0_m, decel, ramp_s)


def stopping_distance(v0_ms, decel, ramp_s):
    return braking_distance(v0_ms, decel, ramp_s)


def bisect_ponr(collides, lo_ms, hi_ms, tol_ms=2.0):
    """Largest latency (ms) at which `collides(latency_ms)` is still False; collisions are monotone in latency.

    Returns None if even lo_ms collides, hi_ms if hi_ms is still safe."""
    if collides(lo_ms):
        return None
    if not collides(hi_ms):
        return hi_ms
    while hi_ms - lo_ms > tol_ms:
        mid = (lo_ms + hi_ms) / 2
        lo_ms, hi_ms = (lo_ms, mid) if collides(mid) else (mid, hi_ms)
    return lo_ms


def summarise(rows):
    """rows: dicts with carla_ms, assumed_ms, fitted_ms -> mean absolute error and bias per model."""
    out = {}
    for key in ("assumed_ms", "fitted_ms"):
        errs = [r[key] - r["carla_ms"] for r in rows if r.get("carla_ms") is not None]
        out[key] = {"mean_abs_error_ms": float(np.mean(np.abs(errs))) if errs else None,
                    "bias_ms": float(np.mean(errs)) if errs else None, "n": len(errs)}
    return out
