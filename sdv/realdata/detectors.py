"""
Semantics-free detectors for real CAN signal data, learned from normal driving only.

  RangeRule   a signal leaves the interval seen in normal driving (plus a margin)
  JumpRule    consecutive samples of a signal differ by more than ever seen (plus a margin)
  PairRule    two signals that move together in normal driving (linear relation) disagree:
              the real-data analogue of a redundant-sensor cross-check
  RateIDS     frame-rate / timing checks per arbitration ID (no payload inspection)

A rule's `alarms(capture)` returns the times (seconds) at which it fires. Selection of which rules to
deploy is done elsewhere, on normal captures only, so attack results are out-of-sample.
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RangeRule:
    can_id: int
    k: int
    lo: float
    hi: float
    kind = "range"

    def alarms(self, cap):
        t, v = cap.series(self.can_id, self.k)
        return t[(v < self.lo) | (v > self.hi)]


@dataclass(frozen=True)
class JumpRule:
    can_id: int
    k: int
    max_step: float
    kind = "jump"

    def alarms(self, cap):
        t, v = cap.series(self.can_id, self.k)
        if len(v) < 2:
            return t[:0]
        return t[1:][np.abs(np.diff(v)) > self.max_step]


@dataclass(frozen=True)
class PairRule:
    a: tuple          # (id, k) of the predictor signal
    b: tuple          # (id, k) of the predicted signal
    slope: float
    intercept: float
    tol: float
    kind = "pair"

    def alarms(self, cap):
        ta, va = cap.series(*self.a)
        tb, vb = cap.series(*self.b)
        if len(va) == 0 or len(vb) == 0:
            return ta[:0]
        # at each update of b, compare with the latest a ...
        pos = np.searchsorted(ta, tb, side="right") - 1
        ok = pos >= 0
        bad_b = np.abs(vb[ok] - (self.slope * va[pos[ok]] + self.intercept)) > self.tol
        # ... and at each update of a, compare with the latest b
        pos = np.searchsorted(tb, ta, side="right") - 1
        ok_a = pos >= 0
        bad_a = np.abs(vb[pos[ok_a]] - (self.slope * va[ok_a] + self.intercept)) > self.tol
        return np.sort(np.concatenate([tb[ok][bad_b], ta[ok_a][bad_a]]))


# ── learning ────────────────────────────────────────────────────────────────
def _all_series(caps, can_id, k):
    return [c.series(can_id, k) for c in caps]


def learn_ranges(caps, margin: float = 0.05, min_samples: int = 50):
    keys = {key for c in caps for key in c.signal_keys()}
    rules = []
    for can_id, k in sorted(keys):
        values = np.concatenate([v for _, v in _all_series(caps, can_id, k)])
        if len(values) < min_samples:
            continue
        lo, hi = float(values.min()), float(values.max())
        pad = margin * (hi - lo) + 1.0
        rules.append(RangeRule(can_id, k, lo - pad, hi + pad))
    return rules


def learn_jumps(caps, factor: float = 1.5, min_samples: int = 50):
    keys = {key for c in caps for key in c.signal_keys()}
    rules = []
    for can_id, k in sorted(keys):
        steps, n = [], 0
        for _, v in _all_series(caps, can_id, k):
            n += len(v)
            if len(v) > 1:
                steps.append(np.abs(np.diff(v)))
        if n < min_samples or not steps:
            continue
        rules.append(JumpRule(can_id, k, float(np.concatenate(steps).max()) * factor + 1.0))
    return rules


def _grid_matrix(caps, keys, dt):
    cols = []
    for cap in caps:
        t0, t1 = float(cap.t[0]), float(cap.t[-1])
        grid = np.arange(t0, t1, dt)
        block = np.full((len(grid), len(keys)), np.nan, dtype=np.float32)
        for j, (can_id, k) in enumerate(keys):
            t, v = cap.series(can_id, k)
            if len(t) == 0:
                continue
            pos = np.searchsorted(t, grid, side="right") - 1
            good = pos >= 0
            block[good, j] = v[pos[good]]
        cols.append(block)
    return np.vstack(cols)


def learn_pairs(caps, r_min: float = 0.999, dt: float = 0.1, min_unique: int = 20,
                partners: int = 3, tol_factor: float = 1.5, max_keys: int = 700):
    """Pairs of signals with a near-perfect linear relation across normal driving."""
    keys = sorted({key for c in caps for key in c.signal_keys()})
    stats = []
    for key in keys:
        values = np.concatenate([v for _, v in _all_series(caps, *key)])
        if len(values) >= 200 and len(np.unique(values)) >= min_unique:
            stats.append((float(values.std()), key))
    keys = [key for _, key in sorted(stats, reverse=True)[:max_keys]]
    if len(keys) < 2:
        return []
    m = _grid_matrix(caps, keys, dt)
    valid = np.isfinite(m).all(axis=1)
    m = m[valid].astype(np.float64)
    if len(m) < 100:
        return []
    z = (m - m.mean(0)) / np.where(m.std(0) > 0, m.std(0), 1.0)
    corr = (z.T @ z) / len(z)
    np.fill_diagonal(corr, 0.0)
    rules, seen = [], set()
    for i in range(len(keys)):
        for j in np.argsort(-np.abs(corr[i]))[:partners]:
            if abs(corr[i, j]) < r_min:
                continue
            a, b = (i, int(j)) if i < j else (int(j), i)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            slope, intercept = np.polyfit(m[:, a], m[:, b], 1)
            if abs(slope) < 1e-9:
                continue
            residual = np.abs(m[:, b] - (slope * m[:, a] + intercept))
            tol = float(residual.max()) * tol_factor + 0.005 * float(np.ptp(m[:, b])) + 1.0
            rules.append(PairRule(keys[a], keys[b], float(slope), float(intercept), tol))
    return rules


# ── frame-rate IDS ──────────────────────────────────────────────────────────
class RateIDS:
    """Per-ID inter-arrival checks; sees only (time, id), never payloads."""
    kind = "rate"

    def __init__(self, short_ratio: float = 0.5, gap_ratio: float = 3.0, max_cv: float = 0.3, min_frames: int = 100):
        self.short_ratio, self.gap_ratio, self.max_cv, self.min_frames = short_ratio, gap_ratio, max_cv, min_frames
        self.period = {}

    def learn(self, captures):
        """captures: iterable of (times, ids) arrays."""
        gaps = {}
        for t, ids in captures:
            for can_id in np.unique(ids):
                tt = t[ids == can_id]
                if len(tt) > 1:
                    gaps.setdefault(int(can_id), []).append(np.diff(tt))
        for can_id, parts in gaps.items():
            g = np.concatenate(parts)
            if len(g) + 1 >= self.min_frames and g.mean() > 0 and g.std() / g.mean() <= self.max_cv:
                self.period[can_id] = float(np.median(g))
        return self

    def alarms(self, t, ids):
        out = []
        for can_id, period in self.period.items():
            tt = t[ids == can_id]
            if len(tt) < 2:
                continue
            g = np.diff(tt)
            out.append(tt[1:][(g < self.short_ratio * period) | (g > self.gap_ratio * period)])
        return np.sort(np.concatenate(out)) if out else np.empty(0)
