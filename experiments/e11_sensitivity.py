"""
E11: how much do the conclusions depend on the ASSUMED ECU timings?

The compute-time means (perception 25, decision 15, actuator 25 ms) and jitter are assumptions, not
measurements. Here they are scaled and the headline findings are recomputed:

  * hazard volume per attack family, without and with the radar failover
  * collisions in benign runs (a scenario that is tight at the default timings becomes unsafe when ECUs are slower)
  * analytic bound: violations (must stay 0) and bound/observed ratio

    python experiments/e11_sensitivity.py --scenarios 4 --samples 60
"""
import argparse
import os
import random
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.analysis.bounds import latency_bound_ms
from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.runner import execute
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import ChainParams

GRID = [("0.5x compute", dict(scale=0.5, sigma=0.15)), ("1x (default)", dict(scale=1.0, sigma=0.15)),
        ("1.5x compute", dict(scale=1.5, sigma=0.15)), ("2x compute", dict(scale=2.0, sigma=0.15)),
        ("1x, jitter 0.30", dict(scale=1.0, sigma=0.30))]


def chain_for(scale, sigma, policy):
    d = ChainParams.from_config()
    return replace(d, perception_ms=d.perception_ms * scale, decision_ms=d.decision_ms * scale,
                   actuator_ms=d.actuator_ms * scale, jitter_sigma=sigma, radar=True, mitigation=policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=4)
    ap.add_argument("--samples", type=int, default=60)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    families = list(ALL_ATTACKS)
    print("attack-induced hazard volume per family (policy none -> radar_or); scenarios are tight at the DEFAULT timings")
    print(f"{'timing assumption':<18}{'benign coll.':>13}" + "".join(f"{f[:14]:>16}" for f in families)
          + f"{'bound viol.':>13}{'bound/obs':>11}")
    for label, kw in GRID:
        cn, cr = chain_for(policy="none", **kw), chain_for(policy="radar_or", **kw)
        benign = sum(execute(random_tight_scenario(random.Random(t)), 700 + t, cn)[0].outcome.collision
                     for t in range(40))
        cells, viol, ratios, n_all = [], 0, [], 0
        for family in families:
            h0 = h1 = n = 0
            for t in range(args.scenarios):
                scenario = random_tight_scenario(random.Random(t))
                problem = AttackSearchProblem(family, scenario)
                for i in range(args.samples):
                    u = rng.random(problem.dim)
                    params = problem.decode(u)
                    r0, _ = execute(scenario, t * 1000 + i, cn, attacks=[make_attack(family, **params)])
                    r1, _ = execute(scenario, t * 1000 + i, cr, attacks=[make_attack(family, **params)])
                    b0 = execute(scenario, t * 1000 + i, cn)[0].outcome.collision
                    b1 = execute(scenario, t * 1000 + i, cr)[0].outcome.collision
                    h0 += r0.outcome.collision and not b0       # attack-induced: no collision without the attack
                    h1 += r1.outcome.collision and not b1
                    n += 1
                    for res, ch in ((r0, cn), (r1, cr)):
                        if res.e2e_latency_ms is not None:
                            b = latency_bound_ms(scenario, make_attack(family, **params), ch).total_ms
                            viol += res.e2e_latency_ms > b + 1e-6
                            ratios.append(b / res.e2e_latency_ms)
                            n_all += 1
            cells.append(f"{h0 / n:.0%}->{h1 / n:.0%}")
        print(f"{label:<18}{benign:>10}/40" + "".join(f"{c:>16}" for c in cells)
              + f"{viol:>9}/{n_all}{np.median(ratios):>11.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
