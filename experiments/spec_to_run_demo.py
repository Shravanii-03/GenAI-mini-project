"""
Requirement text -> timing spec -> STL robustness of simulated runs.

The deadline is no longer hard-coded: it comes from the requirement, through the spec
agent (or the regex baseline with --no-llm), and is evaluated on emulated runs as the
robustness of  G(trigger -> F[0,D ms] response).

    python experiments/spec_to_run_demo.py "Brake within 100 ms if an obstacle is detected."
    python experiments/spec_to_run_demo.py "Braking must start within 0.1 s of detection." --no-llm
"""
import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.runner import run_once
from sdv.schemas import Scenario
from sdv.spec import stl
from sdv.spec.regex_baseline import regex_deadline


def spec_from_text(text, use_llm, model):
    if use_llm:
        from sdv.llm.cached import CachedLLM
        from sdv.rag.retrievers import BM25Retriever
        from sdv.spec.agent import extract_spec
        result = extract_spec(text, CachedLLM(model, max_tokens=450), retriever=BM25Retriever())
        if result.spec and result.spec.get("formula"):
            return result.spec, f"LLM spec agent ({model}), valid={result.valid}, repairs={result.repairs}"
    deadline = regex_deadline(text)
    if deadline is None:
        return None, "no deadline could be extracted"
    spec = {"deadline_ms": deadline, "formula": stl.format_formula("obstacle_detected", "brake_applied", deadline)}
    return spec, "regex baseline"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("requirement", nargs="?", default="Brake within 100 ms if an obstacle is detected.")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--runs", type=int, default=200)
    args = ap.parse_args()

    spec, how = spec_from_text(args.requirement, not args.no_llm, args.model)
    print(f"requirement : {args.requirement}\nextracted by: {how}")
    if spec is None:
        return
    print(f"deadline    : {spec['deadline_ms']:g} ms\nformula     : {spec['formula']}")

    print(f"\n{'CPU load':>9}{'mean latency':>14}{'min robustness':>16}{'mean robustness':>17}{'violations':>12}")
    for load in (0.1, 0.3, 0.5, 0.7, 0.9):
        runs = [run_once(Scenario(v0_kmh=60, d0_m=30, cpu_load=load), seed=i) for i in range(args.runs)]
        rho = [stl.robustness_of_run(spec["formula"], r) for r in runs]
        violated = sum(x < 0 for x in rho) / len(rho)
        print(f"{load:>9.1f}{statistics.mean(r.e2e_latency_ms for r in runs):>11.1f} ms{min(rho):>13.1f} ms"
              f"{statistics.mean(rho):>14.1f} ms{violated:>11.0%}")
    print("\nrobustness > 0 satisfies the requirement; its magnitude is the slack in milliseconds.")


if __name__ == "__main__":
    main()
