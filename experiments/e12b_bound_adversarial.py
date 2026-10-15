"""
E12b: adversarial search for a counter-example to the analytic bound under every defence configuration.

A (1+1)-ES tries to maximise (observed latency - bound) over each attack variant's parameters (including flood
segment and key possession). Finding a positive value would mean the bound is unsound for that configuration.

    python experiments/e12b_bound_adversarial.py --scenarios 4 --budget 200
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from e10_bound_validation import GapProblem
from e12_defences import CONFIGS, VARIANTS, chain_for
from sdv.search.methods import EvolutionStrategy, run_search
from sdv.search.problem import random_tight_scenario


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=4)
    ap.add_argument("--budget", type=int, default=200)
    args = ap.parse_args()
    configs = {"none": None, **CONFIGS}
    total = broken = 0
    for cname in configs:
        chain = chain_for(cname) if cname != "none" else chain_for("radar_or").__class__(
            **{**chain_for("radar_or").__dict__, "mitigation": "none"})
        found = 0
        trials = 0
        for label, family, extra in VARIANTS:
            for t in range(args.scenarios):
                problem = GapProblem(family, random_tight_scenario(random.Random(300 + t)), chain_params=chain)
                if extra:
                    base = problem.decode
                    problem.decode = lambda u, b=base, e=extra: {**b(u), **e}
                method = EvolutionStrategy(problem.dim, np.random.default_rng(t), args.budget)
                out = run_search(problem, method, args.budget, base_seed=t * 4099)
                trials += 1
                found += out["first_success"] is not None
        total += trials
        broken += found
        print(f"{cname:<14} searches that found a bound violation: {found}/{trials} ({args.budget} evaluations each)",
              flush=True)
    print(f"total {broken}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
