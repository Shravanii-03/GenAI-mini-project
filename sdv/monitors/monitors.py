"""
Runtime monitors.

A monitor only sees what a node on the bus can see: arrival time, ID, length and
payload. It never sees the sender or the attack flag (see `observe`). All
thresholds are learned from benign runs only (`train`), never from attacks.

Every monitor returns the time (us) of its first alarm, or None.

  DeadlineMonitor     bounded-response property  G(threat -> F[0,D] brake command),
                      STL robustness  rho = D - (t_cmd - t_threat)
  FrequencyIDS        unknown IDs, inter-arrival time, gaps, windowed bus load
  PlausibilityMonitor sensor counter gaps and kinematic consistency of distance
  FusedMonitor        earliest alarm of several monitors
"""
import bisect
import statistics
from collections import namedtuple

from sdv.bus.can_bus import frame_bits
from sdv.system.brake_chain import BRAKE_ID, SENSOR_ID

Observed = namedtuple("Observed", "t_us can_id dlc data")
Context = namedtuple("Context", "end_us t_appear_us bitrate")


def observe(chain):
    """Bus-visible view of a finished run (no sender, no attack label)."""
    frames = [Observed(f.t_rx_us, f.can_id, f.dlc, f.data) for f in chain.bus.log]
    ctx = Context(chain.sim.now, chain.t_appear_us, chain.bus.bitrate)
    return frames, ctx


class Monitor:
    name = "monitor"

    def train(self, observations):
        """observations: list of (frames, ctx) from benign runs."""

    def first_alarm_us(self, frames, ctx):
        raise NotImplementedError


def _quantile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


# ── system-level requirement monitor ────────────────────────────────────────
class DeadlineMonitor(Monitor):
    """Alarm when no brake command appears within `deadline_ms` of an observed threat.

    The threat is the first sensor frame whose *reported* TTC is below the trigger,
    so a monitor on the bus cannot see a threat that has been spoofed away.
    With oracle=True it uses the true obstacle time instead (an upper bound that no
    real monitor could achieve).
    """

    def __init__(self, ttc_trigger_s=2.0, oracle=False, deadline_ms=None):
        self.ttc_trigger_s, self.oracle, self.deadline_ms = ttc_trigger_s, oracle, deadline_ms
        self.name = "deadline_oracle" if oracle else "deadline"

    def _threat_and_cmd(self, frames, ctx):
        threat = ctx.t_appear_us if self.oracle else None
        cmd = None
        for f in frames:
            if threat is None and f.can_id == SENSOR_ID and f.data.get("obstacle"):
                d, v = f.data.get("distance_m"), f.data.get("speed_ms")
                if d is not None and v and d / v <= self.ttc_trigger_s:
                    threat = f.t_us
            if f.can_id == BRAKE_ID and threat is not None and f.t_us >= threat:
                cmd = f.t_us
                break
        return threat, cmd

    def train(self, observations):
        spans = []
        for frames, ctx in observations:
            threat, cmd = self._threat_and_cmd(frames, ctx)
            if threat is not None and cmd is not None:
                spans.append((cmd - threat) / 1000.0)
        if spans and self.deadline_ms is None:
            self.deadline_ms = _quantile(spans, 0.999) * 1.1

    def first_alarm_us(self, frames, ctx):
        threat, cmd = self._threat_and_cmd(frames, ctx)
        if threat is None:
            return None
        deadline_us = threat + int(self.deadline_ms * 1000)
        if cmd is not None and cmd <= deadline_us:
            return None
        return deadline_us if ctx.end_us >= deadline_us else None


# ── frame-level baseline IDS ────────────────────────────────────────────────
class FrequencyIDS(Monitor):
    name = "frequency_ids"

    def __init__(self, short_ratio=0.4, gap_ratio=2.5, load_window_us=20_000, load_margin=1.5,
                 rate_window_us=100_000, rate_tolerance=0.4):
        self.short_ratio, self.gap_ratio = short_ratio, gap_ratio
        self.rate_window_us, self.rate_tolerance = rate_window_us, rate_tolerance
        self.load_window_us, self.load_margin = load_window_us, load_margin
        self.period_us = {}
        self.event_max_count = {}     # aperiodic (event-driven) IDs: max frames per benign run
        self.load_threshold = 1.0

    @staticmethod
    def _by_id(frames):
        out = {}
        for f in frames:
            out.setdefault(f.can_id, []).append(f.t_us)
        return out

    def _window_loads(self, frames, bitrate):
        loads, window, busy = [], [], 0.0
        for f in frames:
            tx = frame_bits(f.dlc) / bitrate * 1e6
            window.append((f.t_us, tx))
            busy += tx
            while window and window[0][0] <= f.t_us - self.load_window_us:
                busy -= window.pop(0)[1]
            loads.append((f.t_us, busy / self.load_window_us))
        return loads

    def train(self, observations):
        gaps, counts = {}, {}
        peaks = []
        for frames, ctx in observations:
            for can_id, times in self._by_id(frames).items():
                gaps.setdefault(can_id, []).extend(b - a for a, b in zip(times, times[1:]))
                counts[can_id] = max(counts.get(can_id, 0), len(times))
            peaks.append(max((u for _, u in self._window_loads(frames, ctx.bitrate)), default=0.0))
        self.period_us = {i: statistics.median(g) for i, g in gaps.items() if len(g) >= 3}
        self.event_max_count = {i: c for i, c in counts.items() if i not in self.period_us}
        self.load_threshold = max(peaks) * self.load_margin if peaks else 1.0

    def first_alarm_us(self, frames, ctx):
        alarms = []
        last, seen_count = {}, {}
        for f in frames:
            period = self.period_us.get(f.can_id)
            if period is None:
                limit = self.event_max_count.get(f.can_id)
                seen_count[f.can_id] = seen_count.get(f.can_id, 0) + 1
                if limit is None or seen_count[f.can_id] > limit:
                    alarms.append(f.t_us)                   # unknown ID, or event ID repeated
                continue
            if f.can_id in last:
                gap = f.t_us - last[f.can_id]
                if gap < self.short_ratio * period:
                    alarms.append(f.t_us)                   # injected / too fast
                elif gap > self.gap_ratio * period:
                    alarms.append(last[f.can_id] + int(self.gap_ratio * period))  # silent too long
            last[f.can_id] = f.t_us
        for can_id, t_last in last.items():                  # ID went silent until the end
            stale = t_last + int(self.gap_ratio * self.period_us.get(can_id, float("inf")))
            if stale <= ctx.end_us:
                alarms.append(stale)
        for t, util in self._window_loads(frames, ctx.bitrate):
            if util > self.load_threshold:
                alarms.append(t)
                break
        rate_alarm = self._rate_alarm(frames)
        if rate_alarm is not None:
            alarms.append(rate_alarm)
        return min(alarms) if alarms else None

    def _rate_alarm(self, frames):
        """Message-rate rule for fast periodic IDs: frames per window must match the period."""
        for can_id, times in self._by_id(frames).items():
            period = self.period_us.get(can_id)
            if period is None or period > self.rate_window_us / 5:
                continue                                     # too slow for a stable count
            expected = self.rate_window_us / period
            for i, t in enumerate(times):
                if t < times[0] + self.rate_window_us:
                    continue
                count = i - bisect.bisect_right(times, t - self.rate_window_us) + 1
                if abs(count - expected) > self.rate_tolerance * expected:
                    return t
        return None


# ── content plausibility ────────────────────────────────────────────────────
class PlausibilityMonitor(Monitor):
    """Checks the sensor signal against physics, not against timing."""
    name = "plausibility"

    def __init__(self, window=10, tol_m=0.6, sample_period_s=0.010):
        self.window, self.tol_m, self.sample_period_s = window, tol_m, sample_period_s

    def first_alarm_us(self, frames, ctx):
        history = []                                         # (seq, distance, speed)
        last_seq = None
        for f in frames:
            if f.can_id != SENSOR_ID:
                continue
            seq = f.data.get("seq")
            if seq is not None and last_seq is not None and seq - last_seq > 1:
                return f.t_us                                # counter gap: frames missing
            if seq is not None:
                last_seq = seq
            d, v = f.data.get("distance_m"), f.data.get("speed_ms")
            if d is None or seq is None:
                history.clear()
                continue
            history.append((seq, d, v))
            if len(history) > self.window:
                s0, d0, _ = history[-self.window - 1]
                expected_drop = v * (seq - s0) * self.sample_period_s
                if abs((d - d0) + expected_drop) > self.tol_m:
                    return f.t_us                            # distance does not follow ego motion
        return None


class FusedMonitor(Monitor):
    def __init__(self, monitors, name="fused"):
        self.monitors, self.name = monitors, name

    def train(self, observations):
        for m in self.monitors:
            m.train(observations)

    def first_alarm_us(self, frames, ctx):
        alarms = [a for a in (m.first_alarm_us(frames, ctx) for m in self.monitors) if a is not None]
        return min(alarms) if alarms else None
