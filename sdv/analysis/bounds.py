"""
Attack-aware worst-case brake latency, and the attack envelope it proves safe.

For a scenario and an attack instance this module returns an UPPER BOUND on the time from the obstacle
appearing to brake onset, valid for every random draw of sampling phase, sensor noise, compute-time jitter
and background-traffic phase. Comparing the bound with the exact point of no return (plant/longitudinal.py)
gives a proof-style verdict for that attack instance:

    bound <= latest safe latency   ->  PROVEN SAFE      (no collision for any seed)
    otherwise                      ->  UNKNOWN          (the bound is conservative; simulation decides)

Decomposition (all times in ms, measured from obstacle appearance):

    L = T_trig + R_channel + P + R_detect + D + R_cmd + A

    T_trig      time of the sensor frame that first reports TTC <= trigger: one sampling period, plus the
                wait for the true TTC to fall to the trigger, plus noise margin, plus whatever the attack
                adds (a forged distance delays the trigger until the lie stops paying or the window ends)
    R_*         CAN frame response times: non-preemptive fixed-priority response-time analysis
                (Davis, Burns, Bril and Lukkien, 2007) over the catalogued periodic background traffic,
                with the attacker as an additional bounded-budget stream where it outranks the frame
    P, D, A     compute-time WCETs: mean * load factor * exp(z*sigma - sigma^2/2), z = 4 by default

Assumptions that make the bound conditional (reported, never hidden):
    * compute times never exceed that WCET (a draw above z*sigma has probability 3e-5 per stage)
    * the attacker model is the emulator's: a flood is a periodic stream with a frame budget, forging and
      holding frames happen at one gateway, and a redundant channel is attacked only if the family says so
    * the bus model is the emulator's (classical CAN, worst-case stuffing, queued instances never merged)

With the radar failover policies perception triggers on the EARLIER of the two channels, so a single-channel
attack is bounded by the other channel's benign path; bus-level attacks (floods) hit both channels.
"""
import math
from dataclasses import dataclass

from sdv.attacks.library import ALL_ATTACKS, PhantomObstacle
from sdv.bus.can_bus import frame_bits
from sdv.plant.longitudinal import latest_safe_latency_ms
from sdv.system.brake_chain import (BRAKE_ID, DETECT_ID, RADAR_ID, SENSOR_ID, ChainParams)
from sdv.traffic.background import load_periodic_messages

BITRATE = 500_000
TAU_US = 1_000_000 / BITRATE            # one bit time
NOISE_Z = 4.0
FLOOD_FAMILIES = ("dos_flood", "priority_abuse", "low_slow_dos")


def _c_us(dlc=8):
    return math.ceil(frame_bits(dlc) * 1_000_000 / BITRATE)


@dataclass(frozen=True)
class Stream:
    """A periodic interferer: frames of c_us every t_us, with release jitter j_us, at most n frames."""
    can_id: int
    t_us: float
    c_us: float
    j_us: float = 0.0
    n: float = math.inf

    def demand(self, w_us):
        return self.c_us * min(self.n, math.ceil((w_us + self.j_us + TAU_US) / self.t_us))


def _background():
    return [Stream(m["id"], m["cycle_us"], _c_us(m["dlc"]), 0.01 * m["cycle_us"])
            for m in load_periodic_messages(exclude_ids=(SENSOR_ID, DETECT_ID, BRAKE_ID, RADAR_ID))]


def response_time_us(can_id, extra=(), dlc=8, busy_since_us=0.0):
    """Worst-case response time (queueing + transmission) of one frame of `can_id`.

    busy_since_us: the level-`can_id` busy period began this long before the frame was queued (a flood that
    started earlier); every higher-priority stream is then treated as released that much earlier, which is
    the usual way to model backlog in response-time analysis (release jitter)."""
    streams = _background()
    hp = [s for s in streams + list(extra) if s.can_id < can_id]
    if busy_since_us:
        hp = [Stream(s.can_id, s.t_us, s.c_us, s.j_us + busy_since_us, s.n) for s in hp]
    blockers = [s.c_us for s in streams + list(extra) if s.can_id > can_id]
    block = max(blockers + [0.0])
    w = block
    for _ in range(10_000):
        w_next = block + sum(s.demand(w) for s in hp)
        if abs(w_next - w) < 0.5:
            break
        w = w_next
    return w + _c_us(dlc)


def _jitter_hi(sigma, z):
    return math.exp(z * sigma - sigma * sigma / 2)


@dataclass
class Bound:
    total_ms: float
    parts_ms: dict
    assumptions: tuple


def _flood_frames(attack, window_ms):
    """Most frames the attacker can have emitted during a window of `window_ms` of its attack."""
    if attack.name == "low_slow_dos":
        bursts = math.floor(window_ms / attack.period_ms) + 1
        per_burst = math.floor(attack.period_ms * attack.duty * attack.burst_rate_hz / 1000.0) + 1
        return bursts * per_burst
    return math.floor(window_ms * attack.rate_hz / 1000.0) + 1


def _flood_stream(attack, n_frames):
    """The attacker as an interferer with a frame budget (frames queue; they are never dropped)."""
    c = _c_us()
    rate = attack.burst_rate_hz if attack.name == "low_slow_dos" else attack.rate_hz
    return Stream(attack.can_id, 1e6 / rate, c, 0.0, n_frames)


def _trigger_wait_ms(scenario, chain, bias_m=0.0):
    """Upper bound on the sample time (from appearance) of the first frame whose reported TTC <= trigger."""
    v0 = scenario.v0_kmh / 3.6
    ttc_wait = max(0.0, (scenario.d0_m + bias_m + NOISE_Z * chain.sensor_noise_m) / v0 - chain.ttc_trigger_s)
    return chain.sample_period_ms + 1000.0 * ttc_wait


def _benign_trigger_lo_ms(scenario, chain):
    v0 = scenario.v0_kmh / 3.6
    return 1000.0 * max(0.0, (scenario.d0_m - NOISE_Z * chain.sensor_noise_m) / v0 - chain.ttc_trigger_s)


def _window_rel_ms(attack):
    """Attack window relative to obstacle appearance, clipped at the start of the run (500 ms before)."""
    start = max(-500.0, attack.start_offset_ms)
    return start, start + attack.duration_ms


def _channel_trigger_ms(attack, channel, scenario, chain):
    """(upper bound on trigger sample time, extra queueing handled elsewhere) for one channel under `attack`
    (attack=None means the channel is not attacked)."""
    base = _trigger_wait_ms(scenario, chain)
    if attack is None:
        return base
    s_rel, e_rel = _window_rel_ms(attack)
    v0 = scenario.v0_kmh / 3.6
    name = attack.name
    if name == "selective_suppression":
        if attack.k == 1:
            return max(base, e_rel + chain.sample_period_ms)
        return base + chain.sample_period_ms
    if name in ("gateway_delay", "jitter_injection"):
        return base + (attack.delay_ms if e_rel > _benign_trigger_lo_ms(scenario, chain) else 0.0)
    if name in ("masquerade", "dual_masquerade"):
        forged = _trigger_wait_ms(scenario, chain, attack.bias_m) + getattr(attack, "phase_shift_ms", 0.0)
        return min(forged, max(base, e_rel + chain.sample_period_ms))
    if name == "sensor_drift_spoof":
        rho = attack.rate_m_per_s
        if rho >= v0:
            forged = math.inf
        else:
            t_s = (scenario.d0_m + NOISE_Z * chain.sensor_noise_m - v0 * chain.ttc_trigger_s - rho * s_rel / 1000.0) \
                / (v0 - rho)
            forged = max(chain.sample_period_ms, 1000.0 * t_s + chain.sample_period_ms)
        return min(forged, max(base, e_rel + chain.sample_period_ms))
    return base


def _attacked_channels(attack, policy_channels=("sensor", "radar")):
    if attack is None:
        return set()
    if attack.name in FLOOD_FAMILIES:
        return {"bus"}
    if attack.name == "dual_masquerade":
        return {"sensor", "radar"}
    target = getattr(attack, "target_id", getattr(attack, "channel_id", SENSOR_ID))
    return {"radar"} if target == RADAR_ID else {"sensor"}


def latency_bound_ms(scenario, attack=None, chain=None, z=4.0) -> Bound:
    """Upper bound on obstacle-appearance -> brake-onset latency under `attack` (None = benign)."""
    chain = chain or ChainParams.from_config()
    if isinstance(attack, PhantomObstacle):
        raise ValueError("phantom_obstacle is an availability attack; the latency bound does not apply")
    sigma = chain.jitter_sigma
    load = 1.0 + chain.load_gain * scenario.cpu_load ** 2
    jhi = _jitter_hi(sigma, z)
    P = chain.perception_ms * load * jhi
    D = chain.decision_ms * load * jhi
    A = chain.actuator_ms * jhi
    hit = _attacked_channels(attack)
    flood = attack is not None and attack.name in FLOOD_FAMILIES

    extra_by_hop = {}
    pre_ms = 0.0
    n_after = 0
    hp_all = [x for x in _background() if x.can_id < RADAR_ID]
    w_ms = 0.0
    if flood:
        s_rel, e_rel = _window_rel_ms(attack)
        pre_ms = max(0.0, -s_rel)                                  # flood time that elapsed before the obstacle appeared
        n_all = _flood_frames(attack, attack.duration_ms)
        # busy period of the flood: attacker work plus the higher-priority background work released within it.
        # Frames are queued, never dropped, so it can outlive the flood (and the obstacle's appearance).
        work_us = n_all * _c_us()
        w_us = work_us
        for _ in range(10_000):
            w_next = work_us + sum(x.demand(w_us) for x in hp_all)
            if abs(w_next - w_us) < 0.5:
                break
            w_us = w_next
        w_ms = w_us / 1000.0
        d_eff = w_ms - pre_ms                                      # busy time still ahead when the obstacle appears
        if d_eff > 0:
            n_after = 1
            extra = [_flood_stream(attack, n_all)]
            extra_by_hop = {SENSOR_ID: extra, RADAR_ID: extra, DETECT_ID: extra, BRAKE_ID: extra}
        else:
            pre_ms = 0.0

    def resp(can_id):
        return response_time_us(can_id, extra_by_hop.get(can_id, ()), busy_since_us=pre_ms * 1000) / 1000.0

    def resp0(can_id):
        return response_time_us(can_id) / 1000.0

    policy = chain.mitigation
    channels = {"sensor": SENSOR_ID} if policy == "none" else {"sensor": SENSOR_ID, "radar": RADAR_ID}
    paths = {}
    for name, can_id in channels.items():
        under = name in hit
        t_trig = _channel_trigger_ms(attack if (under and not flood) else None, name, scenario, chain)
        paths[name] = t_trig + resp(can_id)
    entry = min(paths.values())

    after = resp(DETECT_ID) + resp(BRAKE_ID)
    total = entry + P + D + A + after
    parts = {"trigger+channel": entry, "perception": P, "decision": D, "actuator": A, "detect+cmd frames": after}

    if flood and n_after > 0:
        # busy-period argument: every attacker frame occupies the bus once, and the higher-priority background
        # frames released while the bus is busy go first; the busy period W that starts with the flood solves
        # W = (attacker work) + (background work released within W). A chain frame sent after the obstacle
        # appears (pre_ms into the flood) leaves by the end of that busy period plus one frame in flight.
        benign = (min(_trigger_wait_ms(scenario, chain) + resp0(c) for c in channels.values())
                  + P + D + A + resp0(DETECT_ID) + resp0(BRAKE_ID))
        cap = benign + max(0.0, d_eff) + _c_us() / 1000.0
        if cap < total:
            parts["temporal cap applied"] = cap - total
            total = cap

    return Bound(total, parts, (
        f"compute times <= WCET (z={z})", "attacker model as emulated", "emulated CAN bus (worst-case stuffing)"))


def proven_safe(scenario, attack=None, chain=None, z=4.0):
    """True when the bound shows no collision is possible for this attack instance, for any seed."""
    return latency_bound_ms(scenario, attack, chain, z).total_ms <= latest_safe_latency_ms(scenario)


def max_safe_value(scenario, family, key, fixed, chain=None, lo=None, hi=None, steps=40, z=4.0):
    """Largest value of attack parameter `key` (others in `fixed`) that is still proven safe, by bisection
    (the bound is monotone in every capability parameter). None if even the smallest value is not provable."""
    bounds = ALL_ATTACKS[family].PARAM_BOUNDS[key]
    lo = bounds[0] if lo is None else lo
    hi = bounds[1] if hi is None else hi
    make = lambda v: ALL_ATTACKS[family](**{**fixed, key: v})
    if not proven_safe(scenario, make(lo), chain, z):
        return None
    if proven_safe(scenario, make(hi), chain, z):
        return hi
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if proven_safe(scenario, make(mid), chain, z) else (lo, mid)
    return lo
