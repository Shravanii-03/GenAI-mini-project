"""
Attack search problem.

Find attack parameters that make the system fail. Parameters live in the unit
cube [0,1]^d and are decoded to each family's declared bounds, so every search
method works on the same normalised space.

Objectives are robustness values in milliseconds (negative = success):

  hazard   f = system margin  (latest safe latency - end-to-end latency)
           f < 0  <=>  the attack causes a collision.
  stealth  f = max(system margin, detector margin)
           f < 0  <=>  collision AND the deployed monitor did not alarm before the
                       point of no return. Conjunction of two negated margins is a
                       max, following STL robustness semantics for 'and'.

Values are clipped to +/-CLIP_MS so that "never braked" or "never alarmed" do not
produce infinities.
"""
import random

import numpy as np

from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.metrics.detection_margin import credited_alarm_us, detection_margin_ms
from sdv.monitors.monitors import observe
from sdv.plant.longitudinal import braking_distance, decel_for_road, ramp_seconds
from sdv.runner import execute
from sdv.schemas import Scenario

CLIP_MS = 1000.0
RESPONSE_MS = 20.0           # assumed time from alarm to mitigation taking effect


def clip(x):
    return max(-CLIP_MS, min(CLIP_MS, x))


def random_tight_scenario(rng: random.Random) -> Scenario:
    """Obstacle placed so a typical benign run is safe but a delayed brake is not."""
    v0_kmh = rng.uniform(50, 70)
    v0 = v0_kmh / 3.6
    stop = braking_distance(v0, decel_for_road("dry"), ramp_seconds())
    d0 = stop + v0 * (0.075 + rng.uniform(0.02, 0.15))
    return Scenario(v0_kmh=v0_kmh, d0_m=d0, road="dry", cpu_load=rng.uniform(0.1, 0.5))


class AttackSearchProblem:
    def __init__(self, family: str, scenario: Scenario, mode: str = "hazard", monitor=None):
        if mode not in ("hazard", "stealth"):
            raise ValueError("mode must be 'hazard' or 'stealth'")
        if mode == "stealth" and monitor is None:
            raise ValueError("stealth mode needs a trained monitor")
        self.family, self.scenario, self.mode, self.monitor = family, scenario, mode, monitor
        self.bounds = dict(ALL_ATTACKS[family].PARAM_BOUNDS)
        self.keys = list(self.bounds)
        self.dim = len(self.keys)
        self.evaluations = 0

    def decode(self, u) -> dict:
        params = {}
        for key, value in zip(self.keys, np.clip(u, 0.0, 1.0)):
            lo, hi = self.bounds[key]
            x = lo + float(value) * (hi - lo)
            params[key] = int(round(x)) if key == "k" else x
        if self.family == "jitter_injection":
            params["seed"] = 0
        return params

    def evaluate(self, u, eval_seed: int) -> dict:
        self.evaluations += 1
        attack = make_attack(self.family, **self.decode(u))
        result, chain = execute(self.scenario, eval_seed, attacks=[attack])
        system = clip(result.margin_ms) if result.margin_ms is not None else -CLIP_MS
        detector = None
        if self.mode == "hazard":
            f = system
        else:
            alarm = credited_alarm_us(self.monitor.first_alarm_us(*observe(chain)),
                                      chain.attack_windows[0][1])
            margin = detection_margin_ms(result, alarm, chain.t_appear_us, RESPONSE_MS)
            detector = clip(margin) if margin is not None else CLIP_MS
            f = max(system, detector)
        return {"f": f, "system_margin": system, "detector_margin": detector, "success": f < 0}
