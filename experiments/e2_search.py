"""
E2: how many simulations does each search method need to find a hazard-causing attack?

For every (mode, family, trial) a random tight scenario is drawn; all methods then
search the same problem on identical noise realisations (the i-th evaluation uses the
same seed for every method). A run succeeds when it finds parameters with f < 0.

  hazard   f < 0 means the attack causes a collision
  stealth  f < 0 means a collision AND the fused monitor did not alarm in time

    python experiments/e2_search.py --budget 50 --trials 15 --seed 1 --out outputs/e2_seed1.csv

Methods: random, grid, q_learning (the original RL component), es, bayes_opt, llm_bo
(Bayesian optimisation warm-started by the cached LLM prior). Where the LLM prior is
unavailable (refused), llm_bo is skipped for that cell and counted.
"""
import argparse
import csv
import multiprocessing as mp
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sdv.attacks.library import ATTACKS
from sdv.metrics.stats import bootstrap_ci, median, wilson_interval
from sdv.monitors.monitors import DeadlineMonitor, FrequencyIDS, FusedMonitor, PlausibilityMonitor, observe
from sdv.runner import execute
from sdv.search.llm_prior import LLMGuidedBO, get_prior
from sdv.search.methods import METHODS, run_search
from sdv.search.problem import AttackSearchProblem, random_tight_scenario

ALL_METHODS = ["random", "grid", "q_learning", "es", "bayes_opt", "llm_bo"]
_STATE = {}


def init_worker():
    """Each worker trains the same fused monitor on the same benign runs."""
    rng = random.Random(777)
    train = [observe(execute(random_tight_scenario(rng), 500_000 + i)[1]) for i in range(60)]
    monitor = FusedMonitor([DeadlineMonitor(), FrequencyIDS(), PlausibilityMonitor()])
    monitor.train(train)
    _STATE["monitor"] = monitor


def run_task(task):
    mode, family, trial, budget, seed = task
    rng = random.Random(f"{seed}-{trial}")
    scenario = random_tight_scenario(rng)
    base_seed = 1_000_000 + trial * 1000
    rows = []
    for index, name in enumerate(ALL_METHODS):
        problem = AttackSearchProblem(family, scenario, mode, monitor=_STATE["monitor"])
        gen = np.random.default_rng([seed, trial, index])
        if name == "llm_bo":
            prior = get_prior(family, mode)
            if not prior:
                rows.append({"mode": mode, "family": family, "trial": trial, "method": name,
                             "status": "llm_unavailable", "first_success": None,
                             "best_f": None, "evaluations": 0})
                continue
            method = LLMGuidedBO(problem.dim, gen, budget, prior=prior)
        else:
            method = METHODS[name](problem.dim, gen, budget=budget)
        out = run_search(problem, method, budget, base_seed=base_seed, stop_on_success=True)
        rows.append({"mode": mode, "family": family, "trial": trial, "method": name, "status": "ok",
                     "first_success": out["first_success"], "best_f": out["best_f"],
                     "evaluations": out["evaluations"]})
    return rows


def summarise(rows, budget):
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    hits = sum(r["first_success"] is not None for r in ok)
    censored = [r["first_success"] if r["first_success"] is not None else budget + 1 for r in ok]
    lo, hi = wilson_interval(hits, n)
    ci = bootstrap_ci(censored)
    return {"n": n, "rate": hits / n if n else float("nan"), "rate_ci": (lo, hi),
            "median_first": median(censored), "first_ci": ci}


def print_table(title, rows, budget):
    print(f"\n{title}")
    print(f"{'method':<12}{'n':>5}{'success rate':>22}{'median sims to first hazard':>34}")
    for name in ALL_METHODS:
        s = summarise([r for r in rows if r["method"] == name], budget)
        if not s["n"]:
            print(f"{name:<12}{0:>5}   (unavailable)")
            continue
        first = f"{s['median_first']:.0f}" + ("+" if s["median_first"] > budget else "")
        print(f"{name:<12}{s['n']:>5}   {s['rate']:>5.2f} [{s['rate_ci'][0]:.2f}, {s['rate_ci'][1]:.2f}]"
              f"{first:>12} [{s['first_ci'][0]:.0f}, {s['first_ci'][1]:.0f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=50)
    ap.add_argument("--trials", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--modes", default="hazard,stealth")
    ap.add_argument("--families", default="all")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    families = list(ATTACKS) if args.families == "all" else args.families.split(",")
    tasks = [(m, f, t, args.budget, args.seed)
             for m in args.modes.split(",") for f in families for t in range(args.trials)]
    print(f"{len(tasks)} tasks x {len(ALL_METHODS)} methods, budget {args.budget}, "
          f"{args.workers} workers")
    with mp.Pool(args.workers, initializer=init_worker) as pool:
        rows = [r for chunk in pool.imap_unordered(run_task, tasks) for r in chunk]

    for mode in args.modes.split(","):
        mode_rows = [r for r in rows if r["mode"] == mode]
        print_table(f"[{mode}] pooled over {len(families)} families x {args.trials} trials",
                    mode_rows, args.budget)
        print(f"\n[{mode}] success rate by family (n={args.trials} per cell)")
        print(f"{'family':<24}" + "".join(f"{m:>11}" for m in ALL_METHODS))
        for fam in families:
            line = f"{fam:<24}"
            for m in ALL_METHODS:
                cell = [r for r in mode_rows if r["family"] == fam and r["method"] == m and r["status"] == "ok"]
                line += f"{sum(r['first_success'] is not None for r in cell) / len(cell):>11.2f}" if cell \
                    else f"{'-':>11}"
            print(line)
    refused = sum(r["status"] == "llm_unavailable" for r in rows)
    print(f"\nLLM prior unavailable in {refused} (mode, family, trial) cells")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"rows written to {args.out}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
