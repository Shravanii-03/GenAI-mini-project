"""
Defence assessment: which attacks does each defence configuration leave open?

For every attack variant (the nine families plus a flood from a node on the safety bus and forging attackers that hold the
signing key) and every defence configuration, sampled attacks are simulated and counted:

    hazard    share of sampled attacks that cause a collision which the same run without the attack does not
    proven    share of sampled attacks the analytic bound proves safe (any seed)
    violated  bound violations (the bound must dominate every simulated latency: expected 0)

`recommend` picks, per variant, the cheapest configuration whose hazard share is at or below `eps`; a variant that no
configuration brings under `eps` is reported as unresolved with the best it achieved. Costs are ordinal (a design
ranking, not a price): none < radar failover < guard < authentication < guard + authentication.
"""
import dataclasses
import random

import numpy as np

from sdv.analysis.bounds import latency_bound_ms
from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.metrics.stats import wilson_interval
from sdv.runner import execute
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import ChainParams

# (label, family, fixed extra parameters)
ATTACK_VARIANTS = [(f, f, {}) for f in ALL_ATTACKS] + [
    ("dos_flood (safety-bus node)", "dos_flood", {"segment": "safety"}),
    ("low_slow_dos (safety-bus node)", "low_slow_dos", {"segment": "safety"}),
    ("masquerade (holds key)", "masquerade", {"holds_key": True}),
    ("dual_masquerade (holds key)", "dual_masquerade", {"holds_key": True}),
]

# ordered by design cost
DEFENCES = [
    ("none", {"mitigation": "none"}),
    ("radar_or", {"mitigation": "radar_or"}),
    ("+guard", {"mitigation": "radar_or", "gateway_guard": True}),
    ("+auth", {"mitigation": "radar_or", "auth": True}),
    ("+guard+auth", {"mitigation": "radar_or", "gateway_guard": True, "auth": True}),
]


def chain_for(overrides: dict) -> ChainParams:
    return dataclasses.replace(ChainParams.from_config(), radar=True, **overrides)


def assess(n_per_variant: int = 40, seed: int = 0, eps: float = 0.02,
           variants=None, defences=None) -> dict:
    variants = variants or ATTACK_VARIANTS
    defences = defences or DEFENCES
    chains = {name: chain_for(kw) for name, kw in defences}
    rng = np.random.default_rng(seed)
    rows, violations, runs = [], 0, 0
    for label, family, extra in variants:
        hits = {name: 0 for name in chains}
        proven = {name: 0 for name in chains}
        for i in range(n_per_variant):
            scenario = random_tight_scenario(random.Random(seed * 1000 + i))      # one fresh scenario per sampled attack
            problem = AttackSearchProblem(family, scenario)
            params = {**problem.decode(rng.random(problem.dim)), **extra}
            run_seed = seed * 100_000 + i
            for name, chain in chains.items():
                attacked = execute(scenario, run_seed, chain, attacks=[make_attack(family, **params)])[0]
                baseline = execute(scenario, run_seed, chain)[0]
                hits[name] += attacked.outcome.collision and not baseline.outcome.collision
                bound = latency_bound_ms(scenario, make_attack(family, **params), chain).total_ms
                proven[name] += bound <= attacked.latest_safe_latency_ms
                if attacked.e2e_latency_ms is not None:
                    violations += attacked.e2e_latency_ms > bound + 1e-6
                    runs += 1
        n = n_per_variant
        rows.append({"variant": label, "family": family, "extra": extra, "n": n,
                     "hazard": {k: hits[k] / n for k in chains},
                     "hazard_upper95": {k: wilson_interval(hits[k], n)[1] for k in chains},
                     "proven_safe": {k: proven[k] / n for k in chains}})
    recommendation = recommend(rows, [name for name, _ in defences], eps)
    return {"n_per_variant": n_per_variant, "seed": seed, "eps": eps, "defences": [name for name, _ in defences],
            "rows": rows, "recommendation": recommendation, "bound_violations": violations, "bound_runs": runs,
            "open": [r["variant"] for r in recommendation if r["config"] is None]}


def recommend(rows: list, order: list, eps: float) -> list:
    out = []
    for row in rows:
        chosen = next((name for name in order if row["hazard"][name] <= eps), None)
        best = min(order, key=lambda name: (row["hazard"][name], order.index(name)))
        shown = chosen if chosen else best
        out.append({"variant": row["variant"], "config": chosen,
                    "hazard_at_choice": row["hazard"][shown],
                    "upper95_at_choice": row.get("hazard_upper95", {}).get(shown),
                    "best_effort": best if chosen is None else None})
    return out


def format_assessment(result: dict) -> str:
    names = result["defences"]
    lines = [f"defence assessment ({result['n_per_variant']} sampled attacks per variant; hazard share by configuration; "
             f"bound violations {result['bound_violations']}/{result['bound_runs']})",
             f"  {'attack variant':<32}" + "".join(f"{n:>13}" for n in names) + "   cheapest sufficient defence"]
    rec = {r["variant"]: r for r in result["recommendation"]}
    for row in result["rows"]:
        r = rec[row["variant"]]
        if r["config"]:
            upper = r.get("upper95_at_choice")
            verdict = r["config"] + (f" (95% upper bound on hazard {upper:.0%})" if upper is not None else "")
        elif r["best_effort"] == names[0]:
            verdict = f"OPEN (no defence helps: {r['hazard_at_choice']:.0%})"
        else:
            verdict = f"OPEN (best {r['best_effort']}: {r['hazard_at_choice']:.0%})"
        lines.append(f"  {row['variant']:<32}" + "".join(f"{row['hazard'][n]:>13.0%}" for n in names) + f"   {verdict}")
    lines.append("  open after every defence: " + (", ".join(result["open"]) or "none"))
    lines.append(f"  (covered = sampled hazard share at most {result['eps']:.0%}; the 95% upper bound shows how little a "
                 f"small sample can certify: with {result['n_per_variant']} samples, zero hazards still allows "
                 f"{wilson_interval(0, result['n_per_variant'])[1]:.0%})")
    return "\n".join(lines)
