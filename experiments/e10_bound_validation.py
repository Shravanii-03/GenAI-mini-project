"""
E10: is the analytic latency bound sound, how tight is it, and what share of the attack space does it prove safe?

For random tight scenarios and uniformly sampled attack parameters (per family, with and without the radar
failover) every simulated run is compared with the bound:

  soundness   observed latency <= bound for every run (violations must be 0), plus an adversarial search that
              tries to maximise (observed - bound)
  tightness   bound / observed latency
  verdict     proven safe (bound <= point of no return) vs hazard (simulated collision) vs unknown:
              "hazard AND proven safe" must be empty; the unknown share is the price of a conservative bound
  headline    largest flood duration proven safe, per flood rate

    python experiments/e10_bound_validation.py --scenarios 6 --samples 120
"""
import argparse
import os
import random
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.analysis.bounds import latency_bound_ms, max_safe_value
from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.plant.longitudinal import latest_safe_latency_ms
from sdv.runner import execute
from sdv.search.methods import EvolutionStrategy, run_search
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import ChainParams


class GapProblem(AttackSearchProblem):
    """Search objective: how far the observed latency gets ABOVE the bound (negative f = bound violated)."""

    def evaluate(self, u, eval_seed):
        self.evaluations += 1
        attack = make_attack(self.family, **self.decode(u))
        result, _ = execute(self.scenario, eval_seed, self.chain_params, attacks=[attack])
        if result.e2e_latency_ms is None:
            return {"f": 0.0, "success": False}
        gap = latency_bound_ms(self.scenario, attack, self.chain_params).total_ms - result.e2e_latency_ms
        return {"f": gap, "success": gap < 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=6)
    ap.add_argument("--samples", type=int, default=120)
    ap.add_argument("--adversarial", type=int, default=250)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    for policy in ("none", "radar_or"):
        chain = replace(ChainParams.from_config(), radar=True, mitigation=policy)
        print(f"\n=== perception policy: {policy} ===")
        print(f"{'family':<22}{'runs':>6}{'violations':>12}{'bound/obs med':>15}{'p95':>7}"
              f"{'hazard':>8}{'proven safe':>13}{'unknown':>9}{'hazard&proven':>15}")
        tot_v = tot_n = 0
        for family in ALL_ATTACKS:
            ratios, hazard, safe, unknown, bad, viol, n = [], 0, 0, 0, 0, 0, 0
            for t in range(args.scenarios):
                scenario = random_tight_scenario(random.Random(t))
                ponr = latest_safe_latency_ms(scenario)
                problem = AttackSearchProblem(family, scenario)
                for i in range(args.samples):
                    u = rng.random(problem.dim)
                    attack = make_attack(family, **problem.decode(u))
                    result, _ = execute(scenario, t * 1000 + i, chain, attacks=[attack])
                    bound = latency_bound_ms(scenario, attack, chain).total_ms
                    n += 1
                    if result.e2e_latency_ms is not None:
                        viol += result.e2e_latency_ms > bound + 1e-6
                        ratios.append(bound / result.e2e_latency_ms)
                    is_hazard = result.outcome.collision
                    is_safe = bound <= ponr
                    hazard += is_hazard
                    safe += is_safe
                    unknown += (not is_safe) and (not is_hazard)
                    bad += is_hazard and is_safe
            tot_v += viol
            tot_n += n
            print(f"{family:<22}{n:>6}{viol:>12}{np.median(ratios):>15.2f}{np.percentile(ratios, 95):>7.2f}"
                  f"{hazard / n:>8.1%}{safe / n:>13.1%}{unknown / n:>9.1%}{bad:>15}")
        print(f"total violations {tot_v}/{tot_n}")

        found = 0
        trials = 0
        for family in ALL_ATTACKS:
            for t in range(5):
                problem = GapProblem(family, random_tight_scenario(random.Random(100 + t)), chain_params=chain)
                method = EvolutionStrategy(problem.dim, np.random.default_rng(t), args.adversarial)
                out = run_search(problem, method, args.adversarial, base_seed=t * 6151)
                trials += 1
                found += out["first_success"] is not None
        print(f"adversarial search for a bound violation: {found}/{trials} searches succeeded "
              f"({args.adversarial} evaluations each)")

    print("\nHeadline: longest flood proven safe (ms), flood starting when the obstacle appears; "
          "scenario 60 km/h, obstacle 24 m, cpu load 0.3")
    from sdv.schemas import Scenario
    scenario = Scenario(v0_kmh=60, d0_m=24, cpu_load=0.3)
    print(f"  latest safe latency {latest_safe_latency_ms(scenario):.0f} ms, benign bound "
          f"{latency_bound_ms(scenario).total_ms:.0f} ms")
    for rate in (500, 1000, 2000, 3000, 4000, 6000):
        v = max_safe_value(scenario, "dos_flood", "duration_ms", {"rate_hz": rate, "start_offset_ms": 0})
        print(f"  flood {rate:>5} frames/s: " + ("not provable even for the shortest flood" if v is None
                                                else f"proven safe up to {v:.0f} ms"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
