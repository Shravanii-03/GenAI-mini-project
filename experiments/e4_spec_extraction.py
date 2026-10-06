"""
E4: natural-language requirement -> timing specification, across conditions and models.

Conditions (all on the same 120 requirements)
  regex           no LLM: '<number> <unit>' pattern (baseline)
  baseline        LLM only
  rag             LLM + retrieved candidate signals and CAN messages
  eager           LLM asked to list signals/IDs from its own knowledge (measures hallucination)
  validator       LLM + deterministic validator with repair loop
  eager_validator eager + validator;  rag_validator  RAG + validator

The first LLM call is identical for baseline/validator and for rag/rag_validator, so the
disk cache makes the validator conditions cost only the repair calls.

    python experiments/e4_spec_extraction.py --model openai/gpt-oss-120b --retriever bm25
"""
import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.llm.cached import CachedLLM
from sdv.rag.kb import kb_ids
from sdv.rag.retrievers import BM25Retriever, LegacyTfidf
from sdv.spec.agent import extract_spec
from sdv.spec.evaluate import aggregate, load_benchmark, score
from sdv.spec.regex_baseline import regex_deadline

CONDITIONS = {
    "baseline": dict(rag=False, validate=False, eager=False),        # told to list only what it is sure of
    "eager": dict(rag=False, validate=False, eager=True),            # asked to list signals from memory
    "rag": dict(rag=True, validate=False, eager=False),
    "validator": dict(rag=False, validate=True, eager=False),
    "eager_validator": dict(rag=False, validate=True, eager=True),
    "rag_validator": dict(rag=True, validate=True, eager=False),
}


def regex_row(item, ids):
    value = regex_deadline(item["text"])
    spec = {"deadline_ms": value, "unresolved": False, "component": "other",
            "formula": None if value is None else f"G(a -> F[0,{value:g} ms] b)"}
    row = score(item, spec, ids)
    row["component_ok"] = False          # regex does not attempt components, signals or CAN IDs
    row["exact"] = False
    return row


def run_condition(name, items, llm, retriever, ids, workers):
    cfg = CONDITIONS[name]

    def one(item):
        result = extract_spec(item["text"], llm, retriever=retriever if cfg["rag"] else None,
                              validate=cfg["validate"], ids=ids, eager=cfg["eager"])
        row = score(item, result.spec, ids)
        row.update(condition=name, repairs=result.repairs, llm_calls=result.llm_calls,
                   valid_first_try=not result.errors_initial, valid_final=result.valid,
                   errors_initial=" | ".join(result.errors_initial)[:300],
                   spec=json.dumps(result.spec))
        return row

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, items))


def print_table(title, groups):
    print(f"\n{title}")
    print(f"{'condition':<15}{'n':>4}{'deadline':>16}{'unresolved':>12}{'component':>11}{'exact':>8}"
          f"{'VSS F1':>8}{'CAN F1':>8}{'invalid VSS':>13}{'invalid CAN':>13}")
    for name, rows in groups.items():
        a = aggregate(rows)
        d = a["deadline_ok_ci"]
        print(f"{name:<15}{a['n']:>4}{a['deadline_ok']:>8.2f} [{d[0]:.2f},{d[1]:.2f}]{a['unresolved_ok']:>9.2f}"
              f"{a['component_ok']:>11.2f}{a['exact']:>8.2f}{a['vss_f1']:>8.2f}{a['can_f1']:>8.2f}"
              f"{a['invalid_vss']:>6}/{a['predicted_vss']:<6}{a['invalid_can']:>6}/{a['predicted_can']:<6}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--retriever", choices=["bm25", "tfidf"], default="bm25")
    ap.add_argument("--conditions", default="baseline,eager,rag,validator,eager_validator,rag_validator")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stride", type=int, default=1, help="use every n-th requirement (keeps all categories)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=450)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    items = load_benchmark()[: args.limit][:: args.stride]
    ids = kb_ids()
    retriever = BM25Retriever() if args.retriever == "bm25" else LegacyTfidf()
    llm = CachedLLM(args.model, max_tokens=args.max_tokens)

    groups = {"regex": [regex_row(i, ids) for i in items]}
    all_rows = []
    for name in args.conditions.split(","):
        rows = run_condition(name, items, llm, retriever, ids, args.workers)
        groups[name] = rows
        all_rows.extend(rows)
        print(f"[{name}] done ({llm.hits} cache hits, {llm.misses} API calls so far)", flush=True)

    print_table(f"{args.model} | retriever={args.retriever} | n={len(items)}", groups)
    print("\nvalidator effect: first-reply validity -> final validity, repairs used")
    for name in ("validator", "eager_validator", "rag_validator"):
        rows = groups.get(name)
        if rows:
            first = sum(r["valid_first_try"] for r in rows) / len(rows)
            final = sum(r["valid_final"] for r in rows) / len(rows)
            print(f"  {name:<15} valid first try {first:.2f} -> after repair {final:.2f}; "
                  f"mean repairs {sum(r['repairs'] for r in rows) / len(rows):.2f}")

    print("\nexact-match accuracy by category")
    tags = sorted({r["tag"] for r in groups["regex"]})
    print(f"{'category':<14}" + "".join(f"{c:>15}" for c in groups) )
    for tag in tags:
        line = f"{tag:<14}"
        for rows in groups.values():
            sel = [r for r in rows if r["tag"] == tag]
            key = "deadline_ok"
            line += f"{sum(r[key] for r in sel) / len(sel):>15.2f}"
        print(line)
    print("(category table shows deadline accuracy)")

    if args.out and all_rows:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            w.writeheader()
            w.writerows(all_rows)
        print(f"\nrows written to {args.out}")


if __name__ == "__main__":
    main()
