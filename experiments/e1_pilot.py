"""
E1 pilot: does ranking detectors by F1 give the same answer as ranking them by
detection margin?

For each attack family, N attack parameter sets are drawn by Latin hypercube from
the family's declared bounds. Every sample is run twice with the same scenario and
seed: once benign, once attacked. Monitors are calibrated on separate benign runs
and see only bus-visible data.

    python experiments/e1_pilot.py --n 40 --seed 1

ASSUMPTIONS (all configurable): ECU compute times, bus load, mitigation response
time, and the scenario distribution below. This is a pilot on an emulated
network, not a result on a real vehicle.
"""
import argparse
import csv
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.attacks.library import ATTACKS, make_attack
from sdv.metrics.detection_margin import classify_run, detection_margin_ms, summarise
from sdv.monitors.monitors import (
    DeadlineMonitor, FrequencyIDS, FusedMonitor, PlausibilityMonitor, observe,
)
from sdv.plant.longitudinal import braking_distance, decel_for_road, ramp_seconds
from sdv.runner import execute
from sdv.schemas import Scenario

RESPONSE_MS = 20.0          # assumed time from alarm to mitigation taking effect


def random_scenario(rng):
    """Obstacle placed so a typical benign run is safe but a delayed brake is not."""
    v0_kmh = rng.uniform(50, 70)
    v0 = v0_kmh / 3.6
    stop = braking_distance(v0, decel_for_road("dry"), ramp_seconds())
    d0 = stop + v0 * (0.075 + rng.uniform(0.02, 0.15))
    return Scenario(v0_kmh=v0_kmh, d0_m=d0, road="dry", cpu_load=rng.uniform(0.1, 0.5))


def latin_hypercube(bounds, n, rng):
    columns = {}
    for key, (lo, hi) in bounds.items():
        cells = [(i + rng.random()) / n for i in range(n)]
        rng.shuffle(cells)
        values = [lo + c * (hi - lo) for c in cells]
        columns[key] = [round(v) for v in values] if key == "k" else values
    return [{k: columns[k][i] for k in bounds} for i in range(n)]


def build_monitors(train_obs):
    deadline, oracle = DeadlineMonitor(), DeadlineMonitor(oracle=True)
    freq, plaus = FrequencyIDS(), PlausibilityMonitor()
    monitors = {
        "deadline": deadline,
        "deadline_oracle": oracle,
        "frequency": freq,
        "plausibility": plaus,
        "timing_only": FusedMonitor([deadline, freq], "timing_only"),
        "fused": FusedMonitor([deadline, freq, plaus]),
    }
    for m in (deadline, oracle, freq, plaus):
        m.train(train_obs)
    return monitors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="attack samples per family")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--train", type=int, default=60, help="benign calibration runs")
    ap.add_argument("--out", default=None, help="optional CSV of per-run rows")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    train_obs = []
    for i in range(args.train):
        _, chain = execute(random_scenario(rng), 100_000 + i)
        train_obs.append(observe(chain))
    monitors = build_monitors(train_obs)

    rows = []
    for family, cls in ATTACKS.items():
        for i, params in enumerate(latin_hypercube(cls.PARAM_BOUNDS, args.n, rng)):
            if family == "jitter_injection":
                params["seed"] = i
            scenario, seed = random_scenario(rng), rng.randrange(10 ** 9)
            benign, bchain = execute(scenario, seed)
            attack = make_attack(family, **params)
            attacked, achain = execute(scenario, seed, attacks=[attack])
            start_us = achain.attack_windows[0][1]
            hazard = (attacked.outcome.collision and not benign.outcome.collision
                      and attacked.latest_safe_latency_ms > 0)
            b_frames, b_ctx = observe(bchain)
            a_frames, a_ctx = observe(achain)
            for name, m in monitors.items():
                a_alarm = m.first_alarm_us(a_frames, a_ctx)
                b_alarm = m.first_alarm_us(b_frames, b_ctx)
                rows.append({
                    "monitor": name, "family": family, "kind": "attack",
                    "outcome": classify_run(a_alarm, start_us), "hazard": hazard,
                    "margin_ms": detection_margin_ms(attacked, a_alarm, achain.t_appear_us, RESPONSE_MS),
                })
                rows.append({
                    "monitor": name, "family": family, "kind": "benign",
                    "outcome": classify_run(b_alarm, None), "hazard": False, "margin_ms": None,
                })

    names = list(monitors)
    overall = {n: summarise([r for r in rows if r["monitor"] == n]) for n in names}
    hazard_runs = next(iter(overall.values()))["hazard_runs"]
    print(f"\nE1 pilot: {args.n} samples x {len(ATTACKS)} families, "
          f"{hazard_runs} attack-induced hazards, mitigation response {RESPONSE_MS:.0f} ms")
    print(f"\n{'monitor':<16}{'recall':>8}{'FPR':>7}{'F1':>7}{'timely':>9}{'med margin':>12}")
    for n in names:
        s = overall[n]
        print(f"{n:<16}{s['recall']:>8.2f}{s['fpr']:>7.2f}{s['f1']:>7.2f}"
              f"{s['timely_rate']:>9.2f}{s['median_margin_ms']:>10.0f}ms")

    deployable = [n for n in names if n != "deadline_oracle"]
    by_f1 = sorted(deployable, key=lambda n: -overall[n]["f1"])
    by_timely = sorted(deployable, key=lambda n: -overall[n]["timely_rate"])
    print("\nranking by F1:             ", " > ".join(by_f1))
    print("ranking by timely-rate:    ", " > ".join(by_timely))
    print("rankings differ:           ", by_f1 != by_timely)

    print("\nPer-family recall / timely rate (deployable monitors)")
    print(f"{'family':<24}" + "".join(f"{n:>22}" for n in deployable))
    for family in ATTACKS:
        line = f"{family:<24}"
        for n in deployable:
            s = summarise([r for r in rows if r["monitor"] == n and r["family"] == family])
            t = "  -" if s["timely_rate"] != s["timely_rate"] else f"{s['timely_rate']:.2f}"
            line += f"{s['recall']:>14.2f} / {t:>5}"
        print(line)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nper-run rows written to {args.out}")


if __name__ == "__main__":
    main()
