"""
Failure analysis for E4 result files.

    python experiments/e4_analyze.py outputs/e4_openai_gpt-oss-120b_bm25.csv [more.csv ...]
"""
import argparse
import collections
import csv
import json


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows:
        for key in ("parsed", "deadline_ok", "unresolved_ok", "component_ok", "exact", "formula_ok",
                    "valid_first_try", "valid_final"):
            r[key] = r[key] == "True"
        for key in ("vss_tp", "vss_fp", "vss_fn", "can_tp", "can_fp", "can_fn", "invalid_vss",
                    "invalid_can", "repairs", "llm_calls"):
            r[key] = int(r[key])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--examples", type=int, default=4)
    args = ap.parse_args()
    bench = {b["id"]: b for b in json.load(open("datasets/benchmark/timing_requirements_bench.json"))}

    for path in args.paths:
        rows = load(path)
        print(f"\n=== {path} ({len(rows)} rows)")
        by_cond = collections.defaultdict(list)
        for r in rows:
            by_cond[r["condition"]].append(r)

        print("\ndeadline accuracy by category")
        tags = sorted({r["tag"] for r in rows})
        print(f"{'category':<14}" + "".join(f"{c:>17}" for c in by_cond))
        for tag in tags:
            print(f"{tag:<14}" + "".join(
                f"{sum(r['deadline_ok'] for r in rs if r['tag'] == tag) / max(1, sum(r['tag'] == tag for r in rs)):>17.2f}"
                for rs in by_cond.values()))

        print("\nwhat the validator caught on the first reply (validator conditions)")
        kinds = collections.Counter()
        for cond in ("validator", "eager_validator", "rag_validator"):
            for r in by_cond.get(cond, []):
                for message in filter(None, r["errors_initial"].split(" | ")):
                    kinds[(cond, message.split(" ")[0] + " " + message.split(" ")[1])] += 1
        for (cond, kind), count in kinds.most_common(10):
            print(f"  {cond:<16}{kind:<30}{count:>4}")

        for cond in ("baseline", "rag_validator"):
            wrong = [r for r in by_cond.get(cond, []) if not r["deadline_ok"]]
            print(f"\n{cond}: {len(wrong)} wrong deadlines; examples")
            for r in wrong[: args.examples]:
                spec = json.loads(r["spec"]) if r["spec"] != "null" else {}
                print(f"  [{r['tag']}] gold={bench[r['id']]['deadline_ms']}  predicted={spec.get('deadline_ms')}  "
                      f"| {bench[r['id']]['text'][:90]}")

        print("\nRAG effect on signal identification (VSS F1 components, all items)")
        for cond, rs in by_cond.items():
            tp, fp, fn = (sum(r[f"vss_{k}"] for r in rs) for k in ("tp", "fp", "fn"))
            ctp, cfp, cfn = (sum(r[f"can_{k}"] for r in rs) for k in ("tp", "fp", "fn"))
            print(f"  {cond:<16} VSS tp/fp/fn {tp}/{fp}/{fn}   CAN tp/fp/fn {ctp}/{cfp}/{cfn}   "
                  f"invalid VSS {sum(r['invalid_vss'] for r in rs)}, invalid CAN {sum(r['invalid_can'] for r in rs)}")


if __name__ == "__main__":
    main()
