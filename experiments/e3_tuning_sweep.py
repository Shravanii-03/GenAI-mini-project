"""
E3: is the F1-optimal detector configuration also the one that flags hazards in time?

Sweep the frequency-IDS and plausibility-monitor settings (36 x 16 = 576 fused
configurations, plus the fixed deadline monitor). Every attack sample is run once
benign and once attacked; each monitor configuration's alarm time is cached, and
fusion is the earliest alarm. Configurations are chosen on the tuning half
(even samples) and reported on the held-out half (odd samples), so the winner's
curse does not inflate the numbers.

    python experiments/e3_tuning_sweep.py --n 60 --seed 1 --out outputs/e3_seed1.csv

Selection rules compared on the tuning half:
  F1-optimal      highest F1
  margin-optimal  highest share of attack-induced hazards flagged before the point of
                  no return, subject to false-alarm rate <= --fpr-cap
"""
import argparse
import copy
import csv
import itertools
import multiprocessing as mp
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.attacks.library import ATTACKS, make_attack
from sdv.metrics.detection_margin import classify_run, credited_alarm_us, detection_margin_ms, summarise
from sdv.metrics.stats import bootstrap_ci
from sdv.monitors.monitors import DeadlineMonitor, FrequencyIDS, PlausibilityMonitor, observe
from sdv.runner import execute
from sdv.search.problem import RESPONSE_MS, random_tight_scenario

FREQ_GRID = {"gap_ratio": [1.5, 2.5, 4.0], "rate_window_us": [50_000, 100_000, 200_000, 400_000],
             "rate_tolerance": [0.2, 0.4, 0.6]}
PLAUS_GRID = {"window": [3, 5, 10, 20], "tol_m": [0.3, 0.6, 1.0, 1.5]}
_STATE = {}


def freq_name(g, w, t):
    return f"freq|gap={g}|win={w // 1000}ms|tol={t}"


def plaus_name(n, tol):
    return f"plaus|win={n}|tol={tol}m"


def latin_hypercube(bounds, n, rng):
    columns = {}
    for key, (lo, hi) in bounds.items():
        cells = [(i + rng.random()) / n for i in range(n)]
        rng.shuffle(cells)
        values = [lo + c * (hi - lo) for c in cells]
        columns[key] = [round(v) for v in values] if key == "k" else values
    return [{k: columns[k][i] for k in bounds} for i in range(n)]


def init_worker():
    rng = random.Random(4242)
    train = [observe(execute(random_tight_scenario(rng), 700_000 + i)[1]) for i in range(60)]
    deadline = DeadlineMonitor()
    deadline.train(train)
    base = FrequencyIDS()
    base.train(train)
    monitors = {"deadline": deadline}
    for g, w, t in itertools.product(*FREQ_GRID.values()):
        m = copy.deepcopy(base)
        m.gap_ratio, m.rate_window_us, m.rate_tolerance = g, w, t
        monitors[freq_name(g, w, t)] = m
    for n, tol in itertools.product(*PLAUS_GRID.values()):
        monitors[plaus_name(n, tol)] = PlausibilityMonitor(window=n, tol_m=tol)
    _STATE["monitors"] = monitors


def run_sample(task):
    family, i, params, scenario, seed = task
    benign, bchain = execute(scenario, seed)
    attacked, achain = execute(scenario, seed, attacks=[make_attack(family, **params)])
    b_frames, b_ctx = observe(bchain)
    a_frames, a_ctx = observe(achain)
    return {
        "family": family, "i": i,
        "hazard": attacked.outcome.collision and not benign.outcome.collision
        and attacked.latest_safe_latency_ms > 0,
        "safe_ms": attacked.latest_safe_latency_ms, "t_appear_us": achain.t_appear_us,
        "start_us": achain.attack_windows[0][1],
        "alarms": {name: (m.first_alarm_us(a_frames, a_ctx), m.first_alarm_us(b_frames, b_ctx))
                   for name, m in _STATE["monitors"].items()},
    }


class _Result:
    """Just enough of RunResult for detection_margin_ms."""
    def __init__(self, safe_ms):
        self.latest_safe_latency_ms = safe_ms


def fuse(*alarms):
    present = [a for a in alarms if a is not None]
    return min(present) if present else None


def rows_for(samples, names):
    rows = []
    for s in samples:
        a = fuse(*(s["alarms"][n][0] for n in names))
        b = fuse(*(s["alarms"][n][1] for n in names))
        rows.append({"outcome": classify_run(a, s["start_us"]), "hazard": s["hazard"],
                     "margin_ms": detection_margin_ms(_Result(s["safe_ms"]), credited_alarm_us(a, s["start_us"]),
                                          s["t_appear_us"], RESPONSE_MS)})
        rows.append({"outcome": classify_run(b, None), "hazard": False, "margin_ms": None})
    return rows


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x, y):
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (sx * sy) if sx and sy else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="attack samples per family")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fpr-cap", type=float, default=0.02)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    tasks = []
    for family, cls in ATTACKS.items():
        for i, params in enumerate(latin_hypercube(cls.PARAM_BOUNDS, args.n, rng)):
            if family == "jitter_injection":
                params["seed"] = i
            tasks.append((family, i, params, random_tight_scenario(rng), rng.randrange(10 ** 9)))
    print(f"{len(tasks)} samples, {len(FREQ_GRID['gap_ratio']) * len(FREQ_GRID['rate_window_us']) * len(FREQ_GRID['rate_tolerance'])}"
          f" x {len(PLAUS_GRID['window']) * len(PLAUS_GRID['tol_m'])} fused configurations")
    with mp.Pool(args.workers, initializer=init_worker) as pool:
        samples = pool.map(run_sample, tasks, chunksize=4)

    tune = [s for k, s in enumerate(samples) if k % 2 == 0]
    hold = [s for k, s in enumerate(samples) if k % 2 == 1]
    configs = [(freq_name(*f), plaus_name(*p))
               for f in itertools.product(*FREQ_GRID.values()) for p in itertools.product(*PLAUS_GRID.values())]

    table = {}
    for fn, pn in configs:
        names = ["deadline", fn, pn]
        table[(fn, pn)] = {"tune": summarise(rows_for(tune, names)), "hold": summarise(rows_for(hold, names))}

    f1s = [table[c]["tune"]["f1"] for c in configs]
    timely = [table[c]["tune"]["timely_rate"] for c in configs]
    print(f"\nhazard runs: tuning half {summarise(rows_for(tune, ['deadline']))['hazard_runs']}, "
          f"held-out half {summarise(rows_for(hold, ['deadline']))['hazard_runs']}")
    print(f"Spearman correlation between F1 and timely-rate across {len(configs)} configurations "
          f"(tuning half): {spearman(f1s, timely):.2f}")

    by_f1 = max(configs, key=lambda c: (table[c]["tune"]["f1"], -table[c]["tune"]["fpr"]))
    eligible = [c for c in configs if table[c]["tune"]["fpr"] <= args.fpr_cap]
    by_margin = max(eligible, key=lambda c: (table[c]["tune"]["timely_rate"], table[c]["tune"]["f1"]))

    print(f"\n{'selection rule':<18}{'configuration':<62}{'tune F1':>8}{'tune timely':>12}"
          f"{'HELD-OUT F1':>13}{'timely':>8}{'FPR':>6}")
    for label, c in (("F1-optimal", by_f1), ("margin-optimal", by_margin)):
        t, h = table[c]["tune"], table[c]["hold"]
        print(f"{label:<18}{c[0] + ' + ' + c[1]:<62}{t['f1']:>8.2f}{t['timely_rate']:>12.2f}"
              f"{h['f1']:>13.2f}{h['timely_rate']:>8.2f}{h['fpr']:>6.2f}")

    def timely_flags(c):
        rows = rows_for(hold, ["deadline", *c])
        return [r["margin_ms"] > 0 for r in rows if r["hazard"] and r["margin_ms"] is not None]
    a, b = timely_flags(by_f1), timely_flags(by_margin)
    diffs = [y - x for x, y in zip(a, b)]
    mean = sum(diffs) / len(diffs) if diffs else float("nan")
    lo, hi = bootstrap_ci(diffs, stat=lambda v: sum(v) / len(v))
    print(f"\nheld-out timely-rate gain of margin-optimal over F1-optimal: {mean:+.3f} "
          f"(95% bootstrap CI [{lo:+.3f}, {hi:+.3f}], {len(diffs)} paired hazard runs)")

    print("\nwhat limits the F1-optimal configuration? attack-induced hazards by family (all samples)")
    print(f"{'family':<24}{'hazards':>8}{'detected':>10}{'in time':>9}   median detection delay")
    names = ["deadline", *by_f1]
    for family in ATTACKS:
        fam = [s for s in samples if s["family"] == family and s["hazard"]]
        if not fam:
            continue
        alarms = [credited_alarm_us(fuse(*(s["alarms"][n][0] for n in names)), s["start_us"]) for s in fam]
        delays = sorted((a - s["start_us"]) / 1000.0 for a, s in zip(alarms, fam) if a is not None)
        in_time = sum(
            (m := detection_margin_ms(_Result(s["safe_ms"]), a, s["t_appear_us"], RESPONSE_MS)) is not None
            and m > 0 for a, s in zip(alarms, fam))
        mid = f"{delays[len(delays) // 2]:.0f} ms after attack start" if delays else "-"
        print(f"{family:<24}{len(fam):>8}{sum(a is not None for a in alarms):>10}{in_time:>9}   {mid}")

    print("\ntimeliness bought with false alarms: margin-optimal configuration at each allowed FPR "
          "(chosen on the tuning half, held-out values shown)")
    print(f"{'FPR cap':>8}{'configs':>9}{'held-out timely':>17}{'held-out F1':>13}{'held-out FPR':>14}")
    for cap in (0.01, 0.02, 0.05, 0.10, 0.20, 0.50):
        pool_ = [c for c in configs if table[c]["tune"]["fpr"] <= cap]
        if not pool_:
            continue
        c = max(pool_, key=lambda c: (table[c]["tune"]["timely_rate"], table[c]["tune"]["f1"]))
        h = table[c]["hold"]
        print(f"{cap:>8.2f}{len(pool_):>9}{h['timely_rate']:>17.2f}{h['f1']:>13.2f}{h['fpr']:>14.2f}")
    h = table[by_f1]["hold"]
    print(f"{'F1-opt':>8}{'':>9}{h['timely_rate']:>17.2f}{h['f1']:>13.2f}{h['fpr']:>14.2f}")

    print("\ntop 5 by tuning F1 (held-out values shown)")
    for c in sorted(configs, key=lambda c: -table[c]["tune"]["f1"])[:5]:
        h = table[c]["hold"]
        print(f"  F1 {h['f1']:.2f}  timely {h['timely_rate']:.2f}  FPR {h['fpr']:.2f}   {c[0]} + {c[1]}")
    print("top 5 by tuning timely-rate with FPR cap (held-out values shown)")
    for c in sorted(eligible, key=lambda c: (-table[c]["tune"]["timely_rate"], -table[c]["tune"]["f1"]))[:5]:
        h = table[c]["hold"]
        print(f"  F1 {h['f1']:.2f}  timely {h['timely_rate']:.2f}  FPR {h['fpr']:.2f}   {c[0]} + {c[1]}")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["freq_config", "plaus_config", "tune_f1", "tune_timely", "tune_fpr",
                        "hold_f1", "hold_timely", "hold_fpr"])
            for c in configs:
                t, h = table[c]["tune"], table[c]["hold"]
                w.writerow([c[0], c[1], t["f1"], t["timely_rate"], t["fpr"], h["f1"], h["timely_rate"], h["fpr"]])
        print(f"\nper-configuration results written to {args.out}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
