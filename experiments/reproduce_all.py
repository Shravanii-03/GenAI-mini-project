"""
Regenerate every experiment table from the repository, offline.

LLM-dependent experiments (E4, E6) run with --offline: they replay the cached model replies in
outputs/llm_cache/ and never call the API, so no key is needed. The full run takes several minutes.

    python experiments/reproduce_all.py            # everything
    python experiments/reproduce_all.py --quick    # skip the slowest searches
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = [
    ("Phase 1 demo (latency vs load, hazard vs distance)", ["experiments/phase1_demo.py"], True),
    ("E1 detector comparison", ["experiments/e1_pilot.py", "--n", "300", "--seed", "1"], True),
    ("E3 detector tuning sweep", ["experiments/e3_tuning_sweep.py", "--n", "60", "--seed", "1"], True),
    ("Hazard volume per attack family", ["experiments/hazard_volume.py"], True),
    ("E2 attack search", ["experiments/e2_search.py", "--budget", "50", "--trials", "20", "--seed", "1"], False),
    ("E4 spec extraction (qwen, cached replies)",
     ["experiments/e4_spec_extraction.py", "--model", "qwen/qwen3.8-27b", "--stride", "2", "--offline",
      "--conditions", "baseline,eager,rag,rag_validator"], True),
    ("E4 spec extraction (gpt-oss-120b, cached replies)",
     ["experiments/e4_spec_extraction.py", "--model", "openai/gpt-oss-120b", "--offline", "--matched",
      "--conditions", "baseline,eager,rag,rag_validator"], True),
    ("E5 retrieval (hand-made KB)", ["experiments/e5_retrieval.py"], True),
    ("E5 retrieval (real VSS v6.1)", ["experiments/e5_retrieval.py", "--real-vss"], True),
    ("E6 red/blue loop (qwen, cached replies)",
     ["experiments/e6_redblue.py", "--seeds", "1,2,3", "--n", "60", "--model", "qwen/qwen3.8-27b", "--offline"],
     False),
    ("End-to-end pipeline", ["-m", "sdv", "--blue", "enumerate", "--n", "40", "--out", "outputs/pipeline_run"], True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip steps marked slow (E2, E6)")
    args = ap.parse_args()
    failures = []
    for title, argv, fast in STEPS:
        if args.quick and not fast:
            print(f"\n=== {title}: skipped (--quick)")
            continue
        print(f"\n{'=' * 78}\n=== {title}\n{'=' * 78}", flush=True)
        start = time.time()
        code = subprocess.call([sys.executable, *argv], cwd=ROOT)
        print(f"--- {title}: {'ok' if code == 0 else f'FAILED (exit {code})'} in {time.time() - start:.0f}s", flush=True)
        if code != 0:
            failures.append(title)
    print("\nAll steps completed." if not failures else f"\nFailed steps: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
