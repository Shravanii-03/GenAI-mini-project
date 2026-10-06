"""
Emulated emergency-braking chain: sensor ECU -> perception ECU -> decision ECU
-> brake actuator, communicating over the emulated CAN bus.

    SENSOR (0x2A0)  periodic frames carrying obstacle distance and ego speed
    DETECT (0x1C0)  perception result
    BRAKE  (0x1A0)  brake command

Perception raises a hazard when the *reported* time-to-collision
(distance / speed) drops below ttc_trigger_s. End-to-end latency is measured
from the obstacle becoming a threat to brake onset, and is the sum of sampling
wait, bus queueing/arbitration, ECU compute and actuator response. It responds
to CPU load, background traffic and anything an attacker does on the bus.

Compute-time means are ASSUMED parameters (config.yaml, section "chain") until
they are calibrated against measurements of real code.
"""
import math
import random
from dataclasses import dataclass

import config
from sdv.bus.can_bus import CanBus
from sdv.schemas import CanFrame, Scenario
from sdv.sim.engine import Simulator
from sdv.traffic.background import BackgroundTraffic

SENSOR_ID = 0x2A0
DETECT_ID = 0x1C0
BRAKE_ID = 0x1A0
RADAR_ID = 0x2B0        # redundant, independent distance sensor (optional)
CHAIN_IDS = (SENSOR_ID, DETECT_ID, BRAKE_ID, RADAR_ID)


@dataclass
class ChainParams:
    sample_period_ms: float = 10.0
    perception_ms: float = 25.0
    decision_ms: float = 15.0
    actuator_ms: float = 25.0
    jitter_sigma: float = 0.15
    load_gain: float = 1.5
    appear_time_ms: float = 500.0
    timeout_ms: float = 2000.0
    ttc_trigger_s: float = 2.0
    tail_ms: float = 100.0
    sensor_noise_m: float = 0.1
    radar: bool = False             # add the redundant radar channel (used by monitors, not by perception)
    radar_noise_m: float = 0.1

    @classmethod
    def from_config(cls):
        d = cls()
        return cls(**{k: config.get(f"chain.{k}", getattr(d, k)) for k in d.__dict__})


class BrakeChain:
    def __init__(self, scenario: Scenario, seed: int, params: ChainParams = None,
                 attacks=(), background: bool = True):
        self.scenario = scenario
        self.params = params or ChainParams.from_config()
        self.rng = random.Random(seed)
        self.sim = Simulator()
        self.bus = CanBus(self.sim)
        self.t_appear_us = int(self.params.appear_time_ms * 1000)
        self.timeline = {}              # event name -> absolute time (us)
        self.brake_onset_us = None
        self.attacks = list(attacks)
        self.attack_windows = []        # (name, start_us, end_us) filled by attacks
        self.background = BackgroundTraffic(self.sim, self.bus, self.rng, CHAIN_IDS) if background else None
        self._noise_rng = random.Random(seed + 7919)   # separate stream: noise never perturbs timing draws
        self._seq = 0
        self._radar_rng = random.Random(seed + 104729)   # separate stream: radar never perturbs other draws
        self._radar_seq = 0
        self._detected = False
        self._cmd_started = False
        self._cmd_received = False
        self.bus.subscribe(self._on_frame)

    # ── timing helpers ──────────────────────────────────────────────────────
    def _jitter(self) -> float:
        s = self.params.jitter_sigma
        return math.exp(self.rng.gauss(-s * s / 2, s))

    def _compute_us(self, mean_ms: float, load_scaled: bool = True) -> int:
        factor = 1.0
        if load_scaled:
            factor += self.params.load_gain * self.scenario.cpu_load ** 2
        return int(mean_ms * 1000 * factor * self._jitter())

    # ── ECU behaviour ───────────────────────────────────────────────────────
    def _sensor_tick(self):
        now = self.sim.now
        seen = now >= self.t_appear_us
        elapsed_s = max(0, now - self.t_appear_us) / 1e6
        v0 = self.scenario.v0_kmh / 3.6
        true_d = max(0.0, self.scenario.d0_m - v0 * elapsed_s)
        frame = CanFrame(
            can_id=SENSOR_ID, src="sensor",
            data={
                "seq": self._seq,
                "obstacle": seen,
                "distance_m": true_d + self._noise_rng.gauss(0, self.params.sensor_noise_m) if seen else None,
                "speed_ms": v0,
            },
        )
        self._seq += 1
        self.bus.send(frame)
        self.sim.schedule(int(self.params.sample_period_ms * 1000), self._sensor_tick)

    def _radar_tick(self):
        now = self.sim.now
        seen = now >= self.t_appear_us
        elapsed_s = max(0, now - self.t_appear_us) / 1e6
        v0 = self.scenario.v0_kmh / 3.6
        true_d = max(0.0, self.scenario.d0_m - v0 * elapsed_s)
        self.bus.send(CanFrame(
            can_id=RADAR_ID, src="radar",
            data={
                "seq": self._radar_seq,
                "obstacle": seen,
                "distance_m": true_d + self._radar_rng.gauss(0, self.params.radar_noise_m) if seen else None,
                "speed_ms": v0,
            },
        ))
        self._radar_seq += 1
        self.sim.schedule(int(self.params.sample_period_ms * 1000), self._radar_tick)

    def _send_detect(self):
        self.timeline["detect_enq"] = self.sim.now
        self.bus.send(CanFrame(can_id=DETECT_ID, src="perception", data={"hazard": True}))

    def _send_cmd(self):
        self.timeline["cmd_enq"] = self.sim.now
        self.bus.send(CanFrame(can_id=BRAKE_ID, src="decision", data={"brake": True}))

    def _brake_onset(self):
        self.brake_onset_us = self.sim.now
        self.timeline["brake_onset"] = self.sim.now
        self.sim.schedule(int(self.params.tail_ms * 1000), self.sim.stop)

    def _reported_ttc(self, frame: CanFrame):
        d, v = frame.data.get("distance_m"), frame.data.get("speed_ms")
        if d is None or not v or v <= 0:
            return None
        return d / v

    def _on_frame(self, frame: CanFrame):
        now = self.sim.now
        if frame.can_id == SENSOR_ID and frame.data.get("obstacle") and not self._detected:
            ttc = self._reported_ttc(frame)
            if ttc is not None and ttc <= self.params.ttc_trigger_s:
                self._detected = True
                self.timeline["sensor_enq"] = frame.t_enqueued_us
                self.timeline["sensor_rx"] = now
                self.sim.schedule(self._compute_us(self.params.perception_ms), self._send_detect)
        elif frame.can_id == DETECT_ID and not self._cmd_started:
            self._cmd_started = True
            self.timeline["detect_rx"] = now
            self.sim.schedule(self._compute_us(self.params.decision_ms), self._send_cmd)
        elif frame.can_id == BRAKE_ID and not self._cmd_received:
            self._cmd_received = True
            self.timeline["cmd_rx"] = now
            self.sim.schedule(
                self._compute_us(self.params.actuator_ms, load_scaled=False), self._brake_onset
            )

    def run(self) -> dict:
        for attack in self.attacks:
            attack.install(self)
        if self.background:
            self.background.start()
        phase_us = int(self.rng.uniform(0, self.params.sample_period_ms * 1000))
        self.sim.schedule_at(phase_us, self._sensor_tick)
        if self.params.radar:
            radar_phase = int(self._radar_rng.uniform(0, self.params.sample_period_ms * 1000))
            self.sim.schedule_at(radar_phase, self._radar_tick)
        self.sim.run(until_us=self.t_appear_us + int(self.params.timeout_ms * 1000))
        return self.timeline
