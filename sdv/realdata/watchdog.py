"""
Authentication + silence watchdog, replayed on real CAN traffic.

The design (see sdv/system/brake_chain.py): a receiver with message authentication rejects any frame whose payload was changed
after the sender signed it; if a periodic message then stops arriving, a watchdog notices the silence. On ROAD's masquerade
captures every frame of the attacked ID inside the attack window is an injected frame (labelled, at the normal rate), so a
receiver that rejects forged frames would see that ID go silent.

IDEALISATION, stated plainly: authentication is assumed perfect (exactly the labelled frames are rejected). What the real data
adds is the TIMING side: how quiet real periodic IDs are in normal driving (the false-trigger rate of the fail-safe) and how
fast the silence is noticed. The detection itself follows from the assumption, not from the data.

Per learned periodic ID the threshold is max(k * period, min_s); the alarm time is the moment the silence exceeds it.
"""
import numpy as np


class SilenceWatchdog:
    kind = "silence-watchdog"

    def __init__(self, k: float = 3.0, min_s: float = 0.03, min_frames: int = 100, max_spread: float = 1.5):
        """max_spread: an ID counts as periodic when the 95th percentile of its gaps is at most max_spread x the median gap
        (a robust test: a few long gaps do not disqualify an ID, they show up later as false triggers)."""
        self.k, self.min_s, self.min_frames, self.max_spread = k, min_s, min_frames, max_spread
        self.period = {}

    def learn(self, captures):
        """captures: iterable of (times, ids) from normal driving."""
        gaps = {}
        for t, ids in captures:
            for can_id in np.unique(ids):
                tt = t[ids == can_id]
                if len(tt) > 1:
                    gaps.setdefault(int(can_id), []).append(np.diff(tt))
        for can_id, parts in gaps.items():
            g = np.concatenate(parts)
            median = float(np.median(g))
            if len(g) + 1 >= self.min_frames and median > 0 and float(np.percentile(g, 95)) <= self.max_spread * median:
                self.period[can_id] = median
        return self

    def threshold(self, can_id: int) -> float:
        return max(self.k * self.period[can_id], self.min_s)

    def alarms(self, t, ids, accepted=None):
        """Alarm times (seconds). `accepted` is a boolean mask of frames that pass authentication (None = all)."""
        out = []
        end = float(t[-1]) if len(t) else 0.0
        for can_id in self.period:
            sel = ids == can_id
            if accepted is not None:
                sel = sel & accepted
            tt = t[sel]
            if len(tt) == 0:
                continue
            thr = self.threshold(can_id)
            gaps = np.diff(tt)
            out.append(tt[:-1][gaps > thr] + thr)
            if end - tt[-1] > thr:                      # silence that runs to the end of the capture
                out.append(np.array([tt[-1] + thr]))
        return np.sort(np.concatenate(out)) if out else np.empty(0)
