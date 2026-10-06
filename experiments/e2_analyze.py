"""Per-family and paired analysis of an E2 results CSV.

    python experiments/e2_analyze.py outputs/e2_seed1.csv --budget 50
"""
import argparse
import collections
import csv
import statistics

METHODS = ["random", "grid", "q_learning", "es", "bayes_opt", "llm_bo"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--budget", type=int, default=50)
    ap.add_argument("--min-rate", type=float, default=0.5, help="families solved by >= this share of random runs")
    args = ap.parse_args()
    rows = list(csv.DictReader(open(args.csv_path)))
    first = lambda r: int(r["first_success"]) if r["first_success"] else args.budget + 1

    for mode in sorted({r["mode"] for r in rows}):
        fams = sorted({r["family"] for r in rows if r["mode"] == mode})
        solvable = [f for f in fams if sum(
            r["first_success"] != "" for r in rows
            if r["mode"] == mode and r["family"] == f and r["method"] == "random"
        ) / max(1, sum(1 for r in rows if r["mode"] == mode and r["family"] == f and r["method"] == "random"))
            >= args.min_rate]
        print(f"\n[{mode}] median sims to first success, families where random succeeds >= {args.min_rate:.0%}")
        print(f"{'family':<24}" + "".join(f"{m:>11}" for m in METHODS))
        for fam in solvable:
            line = f"{fam:<24}"
            for m in METHODS:
                v = [first(r) for r in rows if r["mode"] == mode and r["family"] == fam and r["method"] == m]
                line += f"{statistics.median(v):>11.0f}"
            print(line)
        by = collections.defaultdict(dict)
        for r in rows:
            if r["mode"] == mode and r["family"] in solvable and r["status"] == "ok":
                by[(r["family"], r["trial"])][r["method"]] = first(r)
        print(f"paired per-trial comparison over {len(by)} cells (fewer / tie / more simulations)")
        for a, b in (("llm_bo", "random"), ("llm_bo", "bayes_opt"), ("bayes_opt", "random"), ("es", "random")):
            cells = [v for v in by.values() if a in v and b in v]
            print(f"  {a:<10} vs {b:<10}: {sum(v[a] < v[b] for v in cells):>3} / "
                  f"{sum(v[a] == v[b] for v in cells):>3} / {sum(v[a] > v[b] for v in cells):>3}")


if __name__ == "__main__":
    main()
