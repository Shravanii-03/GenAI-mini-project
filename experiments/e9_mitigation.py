"""
E9: does failing over to the redundant radar prevent the collisions the attacks cause?

Same scenarios, same attack parameters, same seeds, three perception policies (see brake_chain.py):
  none            primary sensor only (the radar is on the bus in every arm, so bus load is identical)
  radar_or        trigger when either channel reports TTC <= trigger
  disagree_brake  radar_or plus a precautionary trigger when the channels disagree

Part A  hazard volume per attack family and policy (uniform sampling), and impact-speed reduction
Part B  cost: benign runs, did the policy change the braking time or trigger without a threat?
Part C  adaptive attacker: (1+1)-ES against the mitigated system, per family

    python experiments/e9_mitigation.py --scenarios 6 --samples 120 --es-budget 150
"""
import argparse
from dataclasses import replace
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.attacks.library import ALL_ATTACKS, PhantomObstacle, make_attack
from sdv.schemas import Scenario
from sdv.system.brake_chain import RADAR_ID, SENSOR_ID
from sdv.metrics.stats import wilson_interval
from sdv.runner import execute
from sdv.search.methods import EvolutionStrategy, run_search
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import ChainParams

POLICIES = ("none", "radar_or", "disagree_brake")


def params_for(policy):
    return replace(ChainParams.from_config(), radar=True, mitigation=policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=6)
    ap.add_argument("--samples", type=int, default=120)
    ap.add_argument("--benign", type=int, default=60)
    ap.add_argument("--es-budget", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    chain_params = {p: params_for(p) for p in POLICIES}

    print("A. hazard volume (share of attack parameter space that causes a collision) and mean impact speed")
    print(f"{'family':<24}" + "".join(f"{p:>26}" for p in POLICIES))
    total = {p: [0, 0] for p in POLICIES}
    for family in ALL_ATTACKS:
        hits = {p: 0 for p in POLICIES}
        impact = {p: [] for p in POLICIES}
        n = 0
        for t in range(args.scenarios):
            scenario = random_tight_scenario(random.Random(t))
            problem = AttackSearchProblem(family, scenario, "hazard")
            for i in range(args.samples):
                u = rng.random(problem.dim)
                n += 1
                for p in POLICIES:
                    attack = make_attack(family, **problem.decode(u))
                    result, _ = execute(scenario, t * 1000 + i, chain_params[p], attacks=[attack])
                    hits[p] += result.outcome.collision
                    impact[p].append(result.outcome.impact_speed_ms)
        line = f"{family:<24}"
        for p in POLICIES:
            lo, hi = wilson_interval(hits[p], n)
            line += f"{hits[p] / n:>8.1%} [{lo:.1%},{hi:.1%}] {np.mean(impact[p]):>5.2f}".rjust(26)
            total[p][0] += hits[p]
            total[p][1] += n
        print(line)
    print(f"{'ALL (equal weight/run)':<24}" + "".join(
        f"{total[p][0] / total[p][1]:>8.1%}".rjust(26) for p in POLICIES))

    print("\nB. cost on benign runs (no attack)")
    base = {}
    for p in POLICIES:
        lat, early, collisions = [], 0, 0
        for t in range(args.benign):
            scenario = random_tight_scenario(random.Random(10_000 + t))
            result, chain = execute(scenario, 50_000 + t, chain_params[p])
            lat.append(result.e2e_latency_ms)
            early += chain.trigger_source == "disagreement"
            collisions += result.outcome.collision
        base[p] = lat
        print(f"  {p:<16} mean e2e latency {np.mean(lat):6.1f} ms  collisions {collisions}/{args.benign}  "
              f"precautionary triggers {early}/{args.benign}")
    for p in POLICIES[1:]:
        diff = np.array(base[p]) - np.array(base["none"])
        print(f"  {p:<16} paired latency change vs none: mean {diff.mean():+.2f} ms, max {diff.max():+.2f} ms")

    print(f"\nC. adaptive attacker: (1+1)-ES, {args.es_budget} evaluations per family and scenario, "
          "against the mitigated system")
    print(f"{'family':<24}" + "".join(f"{p:>18}" for p in POLICIES) + "   (scenarios where a hazard was found)")
    for family in ALL_ATTACKS:
        line = f"{family:<24}"
        for p in POLICIES:
            found = 0
            for t in range(args.scenarios):
                problem = AttackSearchProblem(family, random_tight_scenario(random.Random(t)), "hazard",
                                              chain_params=chain_params[p])
                method = EvolutionStrategy(problem.dim, np.random.default_rng(t), args.es_budget)
                out = run_search(problem, method, args.es_budget, base_seed=t * 7919)
                found += out["first_success"] is not None
            line += f"{found}/{args.scenarios}".rjust(18)
        print(line)

    print("\nD. cost of redundancy: an attacker forges a near obstacle on ONE channel when nothing is in the way "
          "(obstacle 250 m ahead; braking is unwanted)")
    print(f"{'forged channel':<18}" + "".join(f"{p:>18}" for p in POLICIES) + "   (unwanted brake events)")
    for label, channel in (("primary sensor", SENSOR_ID), ("radar", RADAR_ID)):
        line = f"{label:<18}"
        for p in POLICIES:
            fired = 0
            for i in range(args.benign):
                scenario = Scenario(v0_kmh=60, d0_m=250, cpu_load=0.3)
                attack = PhantomObstacle(channel_id=channel, report_m=8.0, start_offset_ms=0, duration_ms=400)
                result, _ = execute(scenario, 90_000 + i, chain_params[p], attacks=[attack])
                fired += result.braked
            line += f"{fired}/{args.benign}".rjust(18)
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
