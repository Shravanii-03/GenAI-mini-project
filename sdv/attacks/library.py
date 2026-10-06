"""
Bus-level attack library.

Every attack acts on the emulated CAN bus, either by injecting frames (a
compromised node) or through a tx filter that drops, delays or modifies frames
(a compromised ECU or gateway). Nothing edits simulator state directly, so any
effect on latency comes from arbitration, queueing or the tampered content.

Each family declares:
  capability     what access the attacker needs (maps to ISO 21434 feasibility)
  PARAM_BOUNDS   ranges used by the search in later phases
Times are relative to the moment the obstacle becomes a threat.
"""
import random

from sdv.schemas import CanFrame
from sdv.system.brake_chain import BRAKE_ID, SENSOR_ID

# Capabilities
NODE = "compromised node on the bus (e.g. via OBD-II or infotainment bridge)"
GATEWAY = "compromised ECU or gateway between a sender and the bus"


class Attack:
    name = "attack"
    capability = ""
    PARAM_BOUNDS = {}

    def __init__(self, start_offset_ms: float = 0.0, duration_ms: float = 200.0):
        self.start_offset_ms = start_offset_ms
        self.duration_ms = duration_ms

    def window_us(self, chain):
        start = max(0, chain.t_appear_us + int(self.start_offset_ms * 1000))
        return start, start + int(self.duration_ms * 1000)

    def install(self, chain):
        start, end = self.window_us(chain)
        chain.attack_windows.append((self.name, start, end))
        self._install(chain, start, end)

    def _install(self, chain, start, end):
        raise NotImplementedError

    def params(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


# ── frame injection ─────────────────────────────────────────────────────────
class DoSFlood(Attack):
    """Back-to-back frames with a very high priority ID; starves everything else."""
    name = "dos_flood"
    capability = NODE
    PARAM_BOUNDS = {"rate_hz": (200, 6000), "duration_ms": (20, 400), "start_offset_ms": (-100, 100)}

    def __init__(self, rate_hz=3000, can_id=0x010, **kw):
        super().__init__(**kw)
        self.rate_hz, self.can_id = rate_hz, can_id

    def _install(self, chain, start, end):
        period_us = max(1, int(1_000_000 / self.rate_hz))

        def emit():
            if chain.sim.now >= end:
                return
            chain.bus.send(CanFrame(can_id=self.can_id, src="attacker", attack=True))
            chain.sim.schedule(period_us, emit)

        chain.sim.schedule_at(start, emit)


class PriorityAbuse(DoSFlood):
    """Flood using a legitimate ID (BRAKE_PRESSURE) that outranks sensor and detect frames.

    The ID is not unknown to the receivers and the rate stays far below a full
    flood, so whitelist and simple rate checks are less likely to fire.
    """
    name = "priority_abuse"
    PARAM_BOUNDS = {"rate_hz": (100, 3000), "duration_ms": (20, 600), "start_offset_ms": (-100, 100)}

    def __init__(self, rate_hz=800, can_id=0x1A3, **kw):
        super().__init__(rate_hz=rate_hz, can_id=can_id, **kw)


class LowSlowDoS(Attack):
    """Duty-cycled flood: bursts followed by silence, keeping average load low."""
    name = "low_slow_dos"
    capability = NODE
    PARAM_BOUNDS = {"duty": (0.05, 0.6), "period_ms": (10, 100),
                    "duration_ms": (50, 600), "start_offset_ms": (-100, 100)}

    def __init__(self, duty=0.3, period_ms=50.0, burst_rate_hz=3000, can_id=0x010, **kw):
        super().__init__(**kw)
        self.duty, self.period_ms, self.burst_rate_hz, self.can_id = duty, period_ms, burst_rate_hz, can_id

    def _install(self, chain, start, end):
        period_us = int(self.period_ms * 1000)
        on_us = int(period_us * self.duty)
        gap_us = max(1, int(1_000_000 / self.burst_rate_hz))

        def emit():
            now = chain.sim.now
            if now >= end:
                return
            phase = (now - start) % period_us
            if phase < on_us:
                chain.bus.send(CanFrame(can_id=self.can_id, src="attacker", attack=True))
                chain.sim.schedule(gap_us, emit)
            else:
                chain.sim.schedule(period_us - phase, emit)

        chain.sim.schedule_at(start, emit)


# ── gateway / compromised-ECU behaviour (tx filters) ────────────────────────
class _FilterAttack(Attack):
    capability = GATEWAY

    def _install(self, chain, start, end):
        chain.bus.add_tx_filter(self._make_filter(start, end))

    def _make_filter(self, start, end):
        raise NotImplementedError


class SelectiveSuppression(_FilterAttack):
    """Drop every k-th frame of one ID (k=1 drops all); looks like a flaky ECU."""
    name = "selective_suppression"
    PARAM_BOUNDS = {"k": (1, 6), "duration_ms": (20, 800), "start_offset_ms": (-100, 100)}

    def __init__(self, k=2, target_id=SENSOR_ID, **kw):
        super().__init__(**kw)
        self.k, self.target_id = int(k), target_id
        self._seen = 0

    def _make_filter(self, start, end):
        def flt(frame, now):
            if start <= now < end and frame.can_id == self.target_id and not frame.attack:
                self._seen += 1
                if self._seen % self.k == 0:
                    frame.attack = True
                    return None, 0
            return frame, 0
        return flt


class SensorDriftSpoof(_FilterAttack):
    """Ramp the reported obstacle distance upward; stays within plausible ranges."""
    name = "sensor_drift_spoof"
    PARAM_BOUNDS = {"rate_m_per_s": (1, 30), "duration_ms": (50, 800), "start_offset_ms": (-400, 50)}

    def __init__(self, rate_m_per_s=10.0, **kw):
        super().__init__(**kw)
        self.rate_m_per_s = rate_m_per_s

    def _make_filter(self, start, end):
        def flt(frame, now):
            if (start <= now < end and frame.can_id == SENSOR_ID
                    and frame.data.get("distance_m") is not None):
                frame.data["distance_m"] += self.rate_m_per_s * (now - start) / 1e6
                frame.attack = True
            return frame, 0
        return flt


class Masquerade(_FilterAttack):
    """Replace the sensor ECU: forged frames at the legitimate period with a constant
    distance bias and a small phase error (imperfect clock synchronisation)."""
    name = "masquerade"
    PARAM_BOUNDS = {"bias_m": (2, 40), "phase_shift_ms": (0, 5),
                    "duration_ms": (50, 800), "start_offset_ms": (-400, 50)}

    def __init__(self, bias_m=15.0, phase_shift_ms=1.0, **kw):
        super().__init__(**kw)
        self.bias_m, self.phase_shift_ms = bias_m, phase_shift_ms

    def _make_filter(self, start, end):
        def flt(frame, now):
            if (start <= now < end and frame.can_id == SENSOR_ID
                    and frame.data.get("distance_m") is not None):
                frame.data["distance_m"] += self.bias_m
                frame.attack = True
                return frame, int(self.phase_shift_ms * 1000)
            return frame, 0
        return flt


class GatewayDelay(_FilterAttack):
    """Hold forwarded frames of one ID for a fixed time."""
    name = "gateway_delay"
    PARAM_BOUNDS = {"delay_ms": (5, 200), "duration_ms": (20, 800), "start_offset_ms": (-100, 100)}

    def __init__(self, delay_ms=50.0, target_id=SENSOR_ID, **kw):
        super().__init__(**kw)
        self.delay_ms, self.target_id = delay_ms, target_id

    def _make_filter(self, start, end):
        def flt(frame, now):
            if start <= now < end and frame.can_id == self.target_id and not frame.attack:
                frame.attack = True
                return frame, int(self.delay_ms * 1000)
            return frame, 0
        return flt


class JitterInjection(_FilterAttack):
    """Random hold time per frame: periodic timing is disturbed, content is untouched."""
    name = "jitter_injection"
    PARAM_BOUNDS = {"delay_ms": (5, 100), "duration_ms": (50, 800), "start_offset_ms": (-100, 100)}

    def __init__(self, delay_ms=30.0, target_id=SENSOR_ID, seed=0, **kw):
        super().__init__(**kw)
        self.delay_ms, self.target_id = delay_ms, target_id
        self._rng = random.Random(seed)

    def _make_filter(self, start, end):
        def flt(frame, now):
            if start <= now < end and frame.can_id == self.target_id and not frame.attack:
                frame.attack = True
                return frame, int(self._rng.uniform(0, self.delay_ms) * 1000)
            return frame, 0
        return flt


ATTACKS = {cls.name: cls for cls in (
    DoSFlood, PriorityAbuse, LowSlowDoS, SelectiveSuppression,
    SensorDriftSpoof, Masquerade, GatewayDelay, JitterInjection,
)}


def make_attack(name: str, **params) -> Attack:
    if name not in ATTACKS:
        raise KeyError(f"unknown attack '{name}'; choose from {sorted(ATTACKS)}")
    return ATTACKS[name](**params)


__all__ = ["ATTACKS", "make_attack", "Attack", "BRAKE_ID"]
