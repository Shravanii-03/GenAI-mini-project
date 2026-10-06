"""
Hazard volume: the fraction of each attack family's parameter space that causes a
collision, estimated by uniform sampling over random tight scenarios.

    python experiments/hazard_volume.py --scenarios 6 --samples 120
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.attacks.library import ATTACKS
from sdv.search.problem import AttackSearchProblem, random_tight_scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=6)
    ap.add_argument("--samples", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    print(f"{'family':<24}{'hazard volume':>15}   most severe hazard found")
    for family in ATTACKS:
        hits, total, best = 0, 0, None
        for t in range(args.scenarios):
            problem = AttackSearchProblem(family, random_tight_scenario(random.Random(t)), "hazard")
            for i in range(args.samples):
                u = rng.random(problem.dim)
                out = problem.evaluate(u, t * 1000 + i)
                total += 1
                if out["success"]:
                    hits += 1
                    if best is None or out["f"] < best[0]:
                        best = (out["f"], problem.decode(u))
        params = {k: round(v, 1) for k, v in best[1].items()} if best else None
        print(f"{family:<24}{hits / total:>14.1%}   {params}")


if __name__ == "__main__":
    main()
