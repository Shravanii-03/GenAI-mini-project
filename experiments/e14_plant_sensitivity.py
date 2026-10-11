"""
E14: do the conclusions survive different braking physics?

E11 varied the ECU timings. The CARLA check (E13) showed that a physics engine's vehicle brakes more weakly than the
emulator's default (about 5.3 m/s^2 at 60 km/h against 7.85 m/s^2), so the braking parameters are varied here. The
friction coefficient sets the deceleration (decel = mu * g). Scenarios are redrawn for each setting (they are built to be
tight for the braking model in use), so the comparison is at constant difficulty, not at constant geometry.

    python experiments/e14_plant_sensitivity.py --scenarios 5 --samples 80
"""
import argparse
import os
import random
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import config
from sdv.analysis.bounds import latency_bound_ms
from sdv.attacks.library import make_attack
from sdv.plant.longitudinal import decel_for_road
from sdv.runner import execute
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import ChainParams

SETTINGS = [("CARLA-like (0.54 g)", 0.54), ("weak (0.65 g)", 0.65), ("default (0.80 g)", 0.80), ("strong (0.90 g)", 0.90)]
CONFIGS = {
    "none": dict(mitigation="none"),
    "radar_or": dict(mitigation="radar_or"),
    "all defences": dict(mitigation="radar_or", gateway_guard=True, auth=True),
}
VARIANTS = [("masquerade", "masquerade", {}), ("gateway_delay", "gateway_delay", {}), ("dos_flood", "dos_flood", {}),
            ("dual_masquerade", "dual_masquerade", {}),
            ("flood (safety-bus node)", "dos_flood", {"segment": "safety"}),
            ("dual (holds key)", "dual_masquerade", {"holds_key": True})]


def set_friction(mu):
    config._load().setdefault("plant", {}).setdefault("friction", {})["dry"] = mu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=5)
    ap.add_argument("--samples", type=int, default=80)
    ap.add_argument("--seed", type=int, default=9)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    original = config.get("plant.friction.dry", 0.8)
    print("attack-induced hazard volume per variant, by defence configuration "
          "(none / radar_or / all defences); benign collisions out of 40")
    print(f"{'braking':<22}{'decel':>7}{'benign':>8}" + "".join(f"{v[0][:22]:>25}" for v in VARIANTS) + f"{'bound viol.':>14}")
    try:
        for label, mu in SETTINGS:
            set_friction(mu)
            chains = {c: replace(ChainParams.from_config(), radar=True, **kw) for c, kw in CONFIGS.items()}
            benign = sum(execute(random_tight_scenario(random.Random(t)), 700 + t, chains["none"])[0].outcome.collision
                         for t in range(40))
            cells, viol, runs = [], 0, 0
            for name, family, extra in VARIANTS:
                hits = {c: 0 for c in CONFIGS}
                n = 0
                for t in range(args.scenarios):
                    scenario = random_tight_scenario(random.Random(t))
                    problem = AttackSearchProblem(family, scenario)
                    for i in range(args.samples):
                        params = {**problem.decode(rng.random(problem.dim)), **extra}
                        n += 1
                        for c, chain in chains.items():
                            result, _ = execute(scenario, t * 1000 + i, chain, attacks=[make_attack(family, **params)])
                            base, _ = execute(scenario, t * 1000 + i, chain)
                            hits[c] += result.outcome.collision and not base.outcome.collision
                            if result.e2e_latency_ms is not None:
                                bound = latency_bound_ms(scenario, make_attack(family, **params), chain).total_ms
                                viol += result.e2e_latency_ms > bound + 1e-6
                                runs += 1
                cells.append(" / ".join(f"{hits[c] / n:.0%}" for c in CONFIGS))
            print(f"{label:<22}{decel_for_road('dry'):>7.2f}{benign:>6}/40" + "".join(f"{c:>25}" for c in cells)
                  + f"{viol:>8}/{runs}", flush=True)
    finally:
        set_friction(original)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
