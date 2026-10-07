"""
End-to-end pipeline.

    requirement text
      -> timing spec (LLM spec agent with RAG and validator, or the regex baseline)
      -> red team: attacks sampled from every family against the baseline monitors
      -> blue team: verified rules (llm | enumerate | random) for the hazards that were missed
      -> red team again against the hardened monitors (residual risk)
      -> evidence bundle, audit and Markdown rendering

    python -m sdv.pipeline --requirement "Brake within 100 ms if an obstacle is detected." --blue enumerate
"""
import argparse
import json
import os
import random

from sdv.attacks.library import ALL_ATTACKS
from sdv.blue.agent import blue_step_llm
from sdv.blue.loop import (
    base_monitors, benign_runs, collect_cases, deployed, known_ids_of, refresh_alarms, timely_rate,
)
from sdv.blue.rules import RuleMonitor
from sdv.blue.synth import enumerate_step, random_step
from sdv.blue.verify import case_outcome, false_alarm_rate
from sdv.evidence.audit import audit
from sdv.evidence.chain import build_bundle
from sdv.evidence.render import render_markdown
from sdv.spec import stl
from sdv.spec.regex_baseline import regex_deadline

FPR_CAP = 0.02


def extract_spec(text: str, llm=None):
    """(spec dict, method). Uses the LLM agent when an llm is given, else the regex baseline."""
    if llm is not None:
        from sdv.rag.retrievers import BM25Retriever
        from sdv.spec.agent import extract_spec as agent_extract
        result = agent_extract(text, llm, retriever=BM25Retriever())
        if result.spec and result.spec.get("deadline_ms") and result.spec.get("formula"):
            return result.spec, f"LLM spec agent (valid={result.valid}, repairs={result.repairs})"
    deadline = regex_deadline(text)
    if deadline is None:
        return None, "no numeric deadline found"
    return ({"deadline_ms": deadline, "component": "other", "trigger": "obstacle_detected",
             "response": "brake_applied",
             "formula": stl.format_formula("obstacle_detected", "brake_applied", deadline)}, "regex baseline")


def run_pipeline(requirement: str, seed: int = 1, n_per_family: int = 40, blue: str = "enumerate",
                 spec_llm=None, blue_llm=None, out_dir: str = None) -> dict:
    spec, method = extract_spec(requirement, spec_llm)
    if spec is None:
        return {"error": method, "requirement": requirement}

    calibration = {"train_seed0": 2_000_000 + seed * 1000, "n_train": 60,
                   "benign_seed0": 2_100_000 + seed * 1000, "n_benign": 60, "fpr_cap": FPR_CAP}
    train = benign_runs(calibration["n_train"], calibration["train_seed0"])
    verify_set = benign_runs(calibration["n_benign"], calibration["benign_seed0"])
    test_benign = benign_runs(80, 2_200_000 + seed * 1000)
    base, known = base_monitors(train), known_ids_of(train)
    families = list(ALL_ATTACKS)

    monitor0 = deployed(base, [])
    hazards0, missed0, stats0 = collect_cases(monitor0, families, n_per_family, random.Random(seed * 7 + 1))
    fit = [dict(c) for c in missed0]

    if blue == "enumerate":
        accepted, n = enumerate_step(verify_set, fit, known, FPR_CAP, 3)
        cost = {"candidates_evaluated": n}
    elif blue == "random":
        accepted, n = random_step(verify_set, fit, known, random.Random(seed + 5), proposals=9, fpr_cap=FPR_CAP)
        cost = {"proposals": n}
    elif blue == "llm":
        if blue_llm is None:
            raise ValueError("blue='llm' needs blue_llm")
        accepted, cost = blue_step_llm(blue_llm, verify_set, fit, known, FPR_CAP, attempts=3)
    elif blue == "none":
        accepted, cost = [], {}
    else:
        raise ValueError("blue must be one of: enumerate, random, llm, none")

    rules = [a["rule"] for a in accepted]
    monitor1 = deployed(base, rules)
    after = [dict(c) for c in hazards0]
    refresh_alarms(after, monitor1)
    _, missed1, stats1 = collect_cases(monitor1, families, n_per_family, random.Random(seed * 7 + 2))

    summary = {
        "requirement": requirement, "spec": spec, "spec_method": method, "seed": seed, "blue": blue,
        "hazards_round0": len(hazards0), "missed_round0": len(missed0),
        "in_time_before": timely_rate([dict(c) for c in hazards0]),
        "in_time_after": timely_rate(after),
        "fpr_before": false_alarm_rate(monitor0, test_benign), "fpr_after": false_alarm_rate(monitor1, test_benign),
        "rules": rules, "blue_cost": cost,
        "round1_missed": {f: s["missed"] for f, s in stats1.items() if s["missed"]},
        "round1_sampled_per_family": n_per_family, "evidence": None,
    }
    residual = {f: f"{s['missed']}/{s['sampled']} sampled attacks still cause a collision with no in-time alarm"
                for f, s in stats1.items() if s["missed"]}
    summary["residual_risk"] = residual

    # Evidence for the first accepted rule, using a missed case that this rule now covers.
    if accepted:
        rule_monitor = RuleMonitor(accepted[0]["rule"])
        hit = next((c for c in missed0
                    if case_outcome(c, _earliest(c["base_alarm"], rule_monitor.first_alarm_us(c["frames"], c["ctx"])))[1]),
                   None)
        if hit is not None:
            bundle = build_bundle({"id": "REQ-1", "text": requirement, "method": method}, spec, hit,
                                  accepted[0], calibration, residual, with_failover=True)
            report = audit(bundle)
            summary["evidence"] = {"audit_passed": report["passed"], "audit_total": report["total"],
                                   "all_passed": report["all_passed"],
                                   "failover_effective": bundle["failover"]["effective"],
                                   "failover_bound_proves_safe": bundle["failover"]["bound_proves_safe"]}
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "evidence_bundle.json"), "w", encoding="utf-8") as f:
                    json.dump(bundle, f, indent=2, default=str)
                with open(os.path.join(out_dir, "evidence.md"), "w", encoding="utf-8") as f:
                    f.write(render_markdown(bundle, report))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "pipeline_summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
    return summary


def _earliest(*alarms):
    present = [a for a in alarms if a is not None]
    return min(present) if present else None


def format_summary(s: dict) -> str:
    if "error" in s:
        return f"pipeline stopped: {s['error']}"
    lines = [
        f"requirement : {s['requirement']}",
        f"spec        : deadline {s['spec']['deadline_ms']:g} ms, {s['spec']['formula']}  [{s['spec_method']}]",
        f"red round 0 : {s['hazards_round0']} attack-induced hazards, {s['missed_round0']} with no in-time alarm",
        f"blue ({s['blue']}) : {len(s['rules'])} verified rule(s) {s['blue_cost']}",
    ]
    lines += [f"              {r}" for r in s["rules"]]
    lines += [
        f"hazards flagged in time: {s['in_time_before']:.2f} -> {s['in_time_after']:.2f}; "
        f"false-alarm rate {s['fpr_before']:.2f} -> {s['fpr_after']:.2f}",
        "residual risk (red round 1, sampled attacks that still cause a collision unnoticed): "
        + (", ".join(f"{f} {n}/{s['round1_sampled_per_family']}" for f, n in s["round1_missed"].items()) or "none"),
    ]
    if s["evidence"]:
        e = s["evidence"]
        lines.append(f"evidence    : audit {e['audit_passed']}/{e['audit_total']} checks re-verified; "
                     f"radar failover {'prevents' if e['failover_effective'] else 'does not prevent'} the case's "
                     f"collision (analytic bound {'proves' if e['failover_bound_proves_safe'] else 'does not prove'} safety)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--requirement", default="Brake within 100 ms if an obstacle is detected.")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=40, help="attack samples per family per round")
    ap.add_argument("--blue", choices=["enumerate", "random", "llm", "none"], default="enumerate")
    ap.add_argument("--llm-model", default=None, help="use this Groq model for the spec agent and/or blue agent")
    ap.add_argument("--out", default="outputs/pipeline_run")
    args = ap.parse_args(argv)
    llm = None
    if args.llm_model:
        from sdv.llm.cached import CachedLLM
        llm = CachedLLM(args.llm_model, max_tokens=700)
    summary = run_pipeline(args.requirement, args.seed, args.n, args.blue,
                           spec_llm=llm, blue_llm=llm, out_dir=args.out)
    print(format_summary(summary))
    if "error" not in summary:
        print(f"\nfiles written to {args.out}/")
    return 0 if "error" not in summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
