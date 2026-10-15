"""
Requirement conformance: can the chain meet a timing requirement, and can that be PROVEN?

The pipeline extracts a deadline from a requirement ("brake within 100 ms ..."). Without an attack, three
statements are possible for a chain configuration:

    proven                   the analytic worst case (sdv/analysis/bounds.py) is at or below the deadline
    met in simulation only   every simulated benign run met it, but the bound is above it
    violated in simulation   some benign run already missed it

The smallest deadline that CAN be proven for this chain is the largest benign bound over the scenarios, which is
the number to quote when a requirement turns out not to be provable. Latency is measured from the obstacle
appearing to brake onset (the convention used throughout the evidence chain).
"""
import dataclasses
import random

import numpy as np

from sdv.analysis.bounds import latency_bound_ms
from sdv.runner import execute
from sdv.search.problem import random_tight_scenario
from sdv.system.brake_chain import ChainParams

CONVENTION = "latency from the obstacle appearing to brake onset; benign runs over tight scenarios"


def default_configs() -> dict:
    base = dataclasses.replace(ChainParams.from_config(), radar=True)
    return {"baseline": dataclasses.replace(base, mitigation="none"),
            "all defences": dataclasses.replace(base, mitigation="radar_or", gateway_guard=True, auth=True)}


def check_requirement(deadline_ms: float, configs: dict = None, n_scenarios: int = 12, runs_per_scenario: int = 3,
                      seed: int = 0, z: float = 4.0) -> dict:
    configs = configs or default_configs()
    out = {"deadline_ms": float(deadline_ms), "convention": CONVENTION, "n_scenarios": n_scenarios,
           "runs": n_scenarios * runs_per_scenario, "configs": {}}
    for name, chain in configs.items():
        bounds, parts, observed = [], [], []
        for i in range(n_scenarios):
            scenario = random_tight_scenario(random.Random(seed * 1000 + i))
            bound = latency_bound_ms(scenario, None, chain, z)
            bounds.append(bound.total_ms)
            parts.append(bound.parts_ms)
            for r in range(runs_per_scenario):
                latency = execute(scenario, seed * 100_000 + i * 10 + r, chain)[0].e2e_latency_ms
                observed.append(float("inf") if latency is None else latency)
        worst = int(np.argmax(bounds))
        bound_max, observed_max = float(max(bounds)), float(max(observed))
        if bound_max <= deadline_ms:
            verdict = "proven"
        elif observed_max <= deadline_ms:
            verdict = "met in simulation only (not provable)"
        else:
            verdict = "violated in simulation"
        out["configs"][name] = {
            "bound_max_ms": bound_max, "bound_median_ms": float(np.median(bounds)),
            "observed_max_ms": observed_max, "observed_mean_ms": float(np.mean(observed)),
            "smallest_provable_deadline_ms": bound_max, "verdict": verdict,
            "worst_case_breakdown_ms": {k: round(float(v), 1) for k, v in parts[worst].items()},
        }
    return out


def format_conformance(result: dict) -> str:
    lines = [f"requirement conformance (deadline {result['deadline_ms']:g} ms; {result['runs']} benign runs over "
             f"{result['n_scenarios']} scenarios)"]
    for name, c in result["configs"].items():
        lines.append(f"  {name:<14} {c['verdict']}: analytic worst case {c['bound_max_ms']:.0f} ms, "
                     f"slowest simulated run {c['observed_max_ms']:.0f} ms")
        if c["verdict"] != "proven":
            lines.append(f"  {'':<14} smallest deadline that can be proven for this chain: "
                         f"{c['smallest_provable_deadline_ms']:.0f} ms")
    return "\n".join(lines)
