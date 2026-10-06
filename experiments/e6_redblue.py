"""
E6: red/blue loop with the redundant radar available.

Round 0  red samples attacks from every family (including the dual-sensor attacker) against the
         baseline monitors; hazards that get no in-time alarm become the blue team's evidence.
Blue     four arms start from the same evidence (half for fitting, half held out):
           none       no new rules
           random     random rules from the grid, 9 proposals, same verifier
           enumerate  exhaustive grid search, same verifier
           llm        LLM proposes rules, same verifier
Round 1  red attacks each hardened monitor again; the evading-hazard volume per family is the
         share of sampled parameter space that still yields a collision with no in-time alarm.

    python experiments/e6_redblue.py --seeds 1,2,3 --model qwen/qwen3.8-27b
"""
import argparse
import copy
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.attacks.library import ALL_ATTACKS
from sdv.blue.agent import blue_step_llm
from sdv.blue.loop import (
    base_monitors, benign_runs, collect_cases, deployed, known_ids_of, refresh_alarms, timely_rate,
)
from sdv.blue.synth import enumerate_step, random_step
from sdv.blue.verify import false_alarm_rate
from sdv.llm.cached import CacheMiss, CachedLLM

ARMS = ["none", "random", "enumerate", "llm"]


def run_seed(seed, args, llm):
    train = benign_runs(60, 1_000_000 + seed * 1000)
    verify_set = benign_runs(60, 1_100_000 + seed * 1000)
    test_benign = benign_runs(100, 1_200_000 + seed * 1000)
    base = base_monitors(train)
    known = known_ids_of(train)
    m0 = deployed(base, [])
    families = list(ALL_ATTACKS)

    hazards0, missed0, stats0 = collect_cases(m0, families, args.n, random.Random(seed * 7 + 1))
    random.Random(seed).shuffle(missed0)
    fit, held = missed0[::2], missed0[1::2]
    result = {"seed": seed, "stats0": stats0, "hazards0": len(hazards0), "missed0": len(missed0),
              "base_fpr": false_alarm_rate(m0, test_benign), "arms": {}}

    for arm in ARMS:
        cases = copy.copy([dict(c) for c in fit])
        rules, cost = [], {}
        if arm == "random":
            accepted, n = random_step(verify_set, cases, known, random.Random(seed + 5), proposals=9)
            rules, cost = [a["rule"] for a in accepted], {"proposals": n}
        elif arm == "enumerate":
            accepted, n = enumerate_step(verify_set, cases, known, 0.02, 3)
            rules, cost = [a["rule"] for a in accepted], {"proposals": n}
        elif arm == "llm":
            if llm is None:
                continue
            try:
                accepted, cost = blue_step_llm(llm, verify_set, cases, known, 0.02, attempts=3)
            except CacheMiss:
                print(f"[seed {seed}] llm arm skipped: reply not in cache (offline)")
                continue
            rules = [a["rule"] for a in accepted]
        cost["to_first_rule"] = accepted[0]["proposal_index"] if arm != "none" and accepted else None
        monitor = deployed(base, rules)

        held_cases = [dict(c) for c in held]
        refresh_alarms(held_cases, monitor)
        all_hazards = [dict(c) for c in hazards0]
        refresh_alarms(all_hazards, monitor)
        _, missed1, stats1 = collect_cases(monitor, families, args.n, random.Random(seed * 7 + 2))
        result["arms"][arm] = {
            "rules": rules, "cost": cost, "held_in_time": timely_rate(held_cases), "held_n": len(held_cases),
            "all_hazard_in_time": timely_rate(all_hazards), "fpr": false_alarm_rate(monitor, test_benign),
            "round1": stats1, "round1_missed": sum(s["missed"] for s in stats1.values()),
            "round1_sampled": sum(s["sampled"] for s in stats1.values()),
        }
    return result


def fmt_rule(rule):
    if rule["type"] == "cross_check":
        return f"cross_check({rule['id_a']},{rule['id_b']}, tol={rule['tol']:g}, skew={rule['max_skew_ms']:g}ms)"
    extras = ", ".join(f"{k}={v}" for k, v in rule.items() if k not in ("type", "id", "field"))
    return f"{rule['type']}({rule.get('id')}, {extras})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--n", type=int, default=60, help="attack samples per family per round")
    ap.add_argument("--model", default="qwen/qwen3.8-27b")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    llm = None if args.no_llm else CachedLLM(args.model, max_tokens=700, offline=args.offline)

    results = [run_seed(int(s), args, llm) for s in args.seeds.split(",")]

    print(f"\nRound 0 (baseline monitors, radar present but unused), {args.n} samples per family")
    print(f"{'family':<24}" + "".join(f"  seed{r['seed']}: hazards/missed" for r in results))
    for fam in ALL_ATTACKS:
        print(f"{fam:<24}" + "".join(f"{r['stats0'][fam]['hazards']:>13}/{r['stats0'][fam]['missed']:<6}   " for r in results))
    print(f"{'ALL':<24}" + "".join(f"{r['hazards0']:>13}/{r['missed0']:<6}   " for r in results))
    print("baseline false-alarm rate on held-out benign runs: "
          + ", ".join(f"{r['base_fpr']:.2f}" for r in results))

    print(f"\nBlue arms (means over {len(results)} seeds; held-out = missed attacks the arm never saw)")
    print(f"{'arm':<11}{'held-out in time':>18}{'all hazards in time':>21}{'FPR':>7}"
          f"{'round-1 evading volume':>24}{'proposals to first rule':>25}")
    for arm in ARMS:
        rows = [r["arms"][arm] for r in results if arm in r["arms"]]
        if not rows:
            print(f"{arm:<11}  (not run)")
            continue
        vol = [x["round1_missed"] / x["round1_sampled"] for x in rows]
        cost = [x["cost"]["to_first_rule"] for x in rows if x["cost"].get("to_first_rule")]
        print(f"{arm:<11}{statistics.mean(x['held_in_time'] for x in rows):>18.2f}"
              f"{statistics.mean(x['all_hazard_in_time'] for x in rows):>21.2f}"
              f"{statistics.mean(x['fpr'] for x in rows):>7.2f}{statistics.mean(vol):>24.3f}"
              f"{(statistics.median(cost) if cost else float('nan')):>25.0f}   (n={len(rows)})")

    print("\nRound 1: evading hazards per family under each arm (missed / sampled), summed over seeds")
    print(f"{'family':<24}" + "".join(f"{a:>12}" for a in ARMS))
    for fam in ALL_ATTACKS:
        line = f"{fam:<24}"
        for arm in ARMS:
            rows = [r["arms"][arm]["round1"][fam] for r in results if arm in r["arms"]]
            line += f"{sum(x['missed'] for x in rows):>6}/{sum(x['sampled'] for x in rows):<5}" if rows else f"{'-':>12}"
        print(line)

    print("\nAccepted rules")
    for r in results:
        for arm in ("enumerate", "llm", "random"):
            if arm in r["arms"]:
                rules = r["arms"][arm]["rules"]
                print(f"  seed {r['seed']} {arm:<10}: " + ("; ".join(fmt_rule(x) for x in rules) or "none"))
    if llm is not None:
        print(f"\nLLM {args.model}: {llm.hits} cache hits, {llm.misses} API calls")
        for r in results:
            if "llm" in r["arms"]:
                c = r["arms"]["llm"]["cost"]
                print(f"  seed {r['seed']}: {c['llm_calls']} calls, {c['proposals']} valid proposals, "
                      f"{c['invalid_proposals']} invalid, {c['rejected_proposals']} rejected by the verifier")


if __name__ == "__main__":
    main()
