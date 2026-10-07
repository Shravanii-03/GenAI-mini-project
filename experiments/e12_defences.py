"""
E12: what is left after redundancy + authentication + a gateway guard?

Defence configurations (all include the radar failover of E9 as the baseline):
  radar_or            OR-voting over primary sensor and radar
  +guard              plus a gateway guard between the untrusted segment and the safety bus
  +auth               plus message authentication (forged frames rejected) and a fail-safe watchdog
  +guard+auth         both

Attack variants beyond the nine families: a flood from a node already ON the safety bus (the guard cannot see it),
and forging attackers that hold the signing key (authentication cannot stop them).

  Part A  hazard volume per variant and configuration, bound soundness on every run
  Part B  benign cost (latency, spurious watchdog triggers)
  Part C  adaptive attacker ((1+1)-ES) per variant and configuration
  Part D  availability cost: unwanted braking when nothing is in the way

    python experiments/e12_defences.py --scenarios 6 --samples 100 --es-budget 100
"""
import argparse
import os
import random
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.analysis.bounds import latency_bound_ms
from sdv.attacks.library import ALL_ATTACKS, PhantomObstacle, make_attack
from sdv.metrics.stats import wilson_interval
from sdv.runner import execute
from sdv.schemas import Scenario
from sdv.search.methods import EvolutionStrategy, run_search
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import RADAR_ID, SENSOR_ID, ChainParams

CONFIGS = {
    "radar_or": dict(mitigation="radar_or"),
    "+guard": dict(mitigation="radar_or", gateway_guard=True),
    "+auth": dict(mitigation="radar_or", auth=True),
    "+guard+auth": dict(mitigation="radar_or", gateway_guard=True, auth=True),
}
VARIANTS = [(f, f, {}) for f in ALL_ATTACKS] + [
    ("dos_flood (safety-bus node)", "dos_flood", {"segment": "safety"}),
    ("low_slow_dos (safety-bus node)", "low_slow_dos", {"segment": "safety"}),
    ("masquerade (holds key)", "masquerade", {"holds_key": True}),
    ("dual_masquerade (holds key)", "dual_masquerade", {"holds_key": True}),
]


def chain_for(name):
    return replace(ChainParams.from_config(), radar=True, **CONFIGS[name])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=6)
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--benign", type=int, default=100)
    ap.add_argument("--es-budget", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    chains = {c: chain_for(c) for c in CONFIGS}

    print("A. hazard volume (share of the attack parameter space that causes a collision)")
    print(f"{'attack variant':<34}" + "".join(f"{c:>22}" for c in CONFIGS))
    violations = runs = 0
    for label, family, extra in VARIANTS:
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
                    hits[c] += result.outcome.collision
                    if result.e2e_latency_ms is not None:
                        bound = latency_bound_ms(scenario, make_attack(family, **params), chain).total_ms
                        violations += result.e2e_latency_ms > bound + 1e-6
                        runs += 1
        line = f"{label:<34}"
        for c in CONFIGS:
            lo, hi = wilson_interval(hits[c], n)
            line += f"{hits[c] / n:>8.1%} [{lo:.1%},{hi:.1%}]".rjust(22)
        print(line)
    print(f"analytic bound violations: {violations}/{runs}")

    print("\nB. cost on benign runs (no attack)")
    base = None
    for c, chain in chains.items():
        lat, wd, coll = [], 0, 0
        for t in range(args.benign):
            scenario = random_tight_scenario(random.Random(10_000 + t))
            result, ch = execute(scenario, 50_000 + t, chain)
            lat.append(result.e2e_latency_ms)
            wd += ch.trigger_source == "watchdog"
            coll += result.outcome.collision
        base = base or lat
        diff = np.array(lat) - np.array(base)
        print(f"  {c:<14} mean latency {np.mean(lat):6.1f} ms  paired change vs radar_or {diff.mean():+.2f} ms  "
              f"collisions {coll}/{args.benign}  watchdog triggers {wd}/{args.benign}")

    print(f"\nC. adaptive attacker: (1+1)-ES, {args.es_budget} evaluations per variant and scenario "
          "(scenarios where a hazard was found)")
    print(f"{'attack variant':<34}" + "".join(f"{c:>14}" for c in CONFIGS))
    for label, family, extra in VARIANTS:
        line = f"{label:<34}"
        for c, chain in chains.items():
            found = 0
            for t in range(args.scenarios):
                problem = AttackSearchProblem(family, random_tight_scenario(random.Random(t)), "hazard",
                                              chain_params=chain)
                if extra:
                    base_decode = problem.decode
                    problem.decode = lambda u, b=base_decode, e=extra: {**b(u), **e}
                method = EvolutionStrategy(problem.dim, np.random.default_rng(t), args.es_budget)
                out = run_search(problem, method, args.es_budget, base_seed=t * 7919)
                found += out["first_success"] is not None
            line += f"{found}/{args.scenarios}".rjust(14)
        print(line)

    print("\nD. availability cost: unwanted braking when nothing is in the way (obstacle 250 m ahead), "
          "attack runs for 400 ms")
    print(f"{'attack':<40}" + "".join(f"{c:>14}" for c in CONFIGS) + "   (unwanted brake events)")
    cases = [
        ("forged near obstacle on radar", lambda: PhantomObstacle(channel_id=RADAR_ID, report_m=8.0,
                                                                   start_offset_ms=0, duration_ms=400)),
        ("forged near obstacle on sensor", lambda: PhantomObstacle(channel_id=SENSOR_ID, report_m=8.0,
                                                                    start_offset_ms=0, duration_ms=400)),
        ("forged near obstacle, holds key", lambda: PhantomObstacle(channel_id=SENSOR_ID, report_m=8.0,
                                                                     holds_key=True, start_offset_ms=0,
                                                                     duration_ms=400)),
        ("both channels corrupted (dual forgery)", lambda: make_attack("dual_masquerade", bias_m=5.0,
                                                                       start_offset_ms=0, duration_ms=400)),
    ]
    for label, make in cases:
        line = f"{label:<40}"
        for c, chain in chains.items():
            fired = 0
            for i in range(args.benign):
                scenario = Scenario(v0_kmh=60, d0_m=250, cpu_load=0.3)
                result, _ = execute(scenario, 90_000 + i, chain, attacks=[make()])
                fired += result.braked
            line += f"{fired}/{args.benign}".rjust(14)
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
