"""
Are the VSS paths an LLM lists from memory fabricated, or real VSS paths missing from our KB?

For every VSS path predicted in the *eager* condition (no retrieval, asked to use its own
knowledge) this classifies it as:
  in_kb        present in the project's hand-made knowledge base
  real_not_kb  exists in the official COVESA VSS v6.1 but not in our KB
  fabricated   exists in neither

    python experiments/e4_hallucination_check.py outputs/e4_*_bm25.csv
"""
import argparse
import collections
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.rag.kb import kb_ids, load_real_vss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--condition", default="eager")
    ap.add_argument("--examples", type=int, default=5)
    args = ap.parse_args()
    kb = kb_ids()["vss"]
    real = {d.id for d in load_real_vss()}

    for path in args.paths:
        counts, fabricated = collections.Counter(), collections.Counter()
        for row in csv.DictReader(open(path, encoding="utf-8")):
            if row["condition"] != args.condition or row["spec"] == "null":
                continue
            for signal in json.loads(row["spec"]).get("vss_signals") or []:
                if signal in kb:
                    counts["in_kb"] += 1
                elif signal in real:
                    counts["real_not_kb"] += 1
                else:
                    counts["fabricated"] += 1
                    fabricated[signal] += 1
        total = sum(counts.values())
        print(f"\n{path}  ({args.condition}: {total} predicted VSS paths)")
        for key in ("in_kb", "real_not_kb", "fabricated"):
            share = counts[key] / total if total else float("nan")
            print(f"  {key:<12}{counts[key]:>5}  ({share:.0%})")
        if fabricated:
            print("  most frequent fabricated paths:",
                  ", ".join(f"{p} x{n}" for p, n in fabricated.most_common(args.examples)))


if __name__ == "__main__":
    main()
