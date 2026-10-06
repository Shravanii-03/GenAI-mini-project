"""
No-LLM baseline: exhaustive grid search over the rule language.

Greedy: evaluate every grid candidate with the same verifier the LLM's proposals face, adopt
the best, update which cases are still missed, repeat. The count of candidates evaluated is the
cost to compare with the number of LLM proposals.
"""
import itertools

from sdv.blue.summary import numeric_ids
from sdv.blue.verify import adopt_rule, uncovered, verify_rule

GRID = {
    "cross_check": {"tol": [0.5, 1.0, 2.0, 3.0, 5.0, 8.0], "max_skew_ms": [5.0, 15.0, 30.0]},
    "jump": {"max_step": [0.5, 1.0, 2.0, 4.0, 8.0]},
    "drift": {"window": [5, 10, 20], "slack_m": [0.0, 0.5, 1.0, 2.0]},
}


def candidates(benign_obs, field="distance_m"):
    ids = numeric_ids(benign_obs, field)
    out = []
    for a, b in itertools.combinations(ids, 2):
        for tol, skew in itertools.product(*GRID["cross_check"].values()):
            out.append({"type": "cross_check", "id_a": hex(a), "id_b": hex(b), "field": field,
                        "tol": tol, "max_skew_ms": skew})
    for i in ids:
        for step in GRID["jump"]["max_step"]:
            out.append({"type": "jump", "id": hex(i), "field": field, "max_step": step})
        for window, slack in itertools.product(*GRID["drift"].values()):
            out.append({"type": "drift", "id": hex(i), "field": field, "window": window, "slack_m": slack})
    return out


def enumerate_step(benign_obs, cases, known_ids, fpr_cap=0.02, max_rules=3):
    """Returns (accepted verdicts, number of candidates evaluated). Mutates cases' base alarms."""
    accepted, evaluated = [], 0
    pool = candidates(benign_obs)
    for _ in range(max_rules):
        if not uncovered(cases):
            break
        best = None
        for rule in pool:
            verdict = verify_rule(rule, benign_obs, cases, known_ids, fpr_cap)
            evaluated += 1
            if verdict["ok"] and (best is None or (verdict["new_timely"], -verdict["fpr"])
                                  > (best["new_timely"], -best["fpr"])):
                best = verdict
        if best is None:
            break
        best["proposal_index"] = evaluated          # candidates evaluated when this rule was chosen
        accepted.append(best)
        adopt_rule(best["rule"], cases)
    return accepted, evaluated


def random_step(benign_obs, cases, known_ids, rng, proposals=9, fpr_cap=0.02):
    """Baseline: random rules from the grid with the same verifier and a fixed proposal budget.

    Separates what an LLM's reasoning adds from what verification alone achieves.
    Returns (accepted verdicts, proposals made). Mutates cases' base alarms.
    """
    pool = candidates(benign_obs)
    accepted = []
    for index in range(1, proposals + 1):
        if not uncovered(cases):
            break
        verdict = verify_rule(rng.choice(pool), benign_obs, cases, known_ids, fpr_cap)
        if verdict["ok"]:
            verdict["proposal_index"] = index
            accepted.append(verdict)
            adopt_rule(verdict["rule"], cases)
    return accepted, proposals
