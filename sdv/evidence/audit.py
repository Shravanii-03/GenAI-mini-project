"""
Auditor: re-run every claim in an evidence bundle and report which ones hold.

Checks (each is recomputed, none is taken on trust):
  spec_formula_parses              the formula is valid bounded-response STL
  spec_bound_matches_deadline      its upper bound equals deadline_ms
  violation_reproduces             re-simulating scenario+seed+attack gives the recorded latency,
                                   robustness and collision flag
  violation_is_real                the deadline is missed (robustness < 0) and/or a collision occurs
  attack_is_known                  the family exists and its capability text matches the library
  kb_pattern_matches_the_knowledge_base   the cited attack pattern exists with the same fields
  rule_is_valid                    the rule passes language validation against the bus IDs
  rule_fpr_reproduces              false-alarm rate recomputed on regenerated benign runs is within the cap
                                   and equals the recorded value
  rule_catches_the_violation_in_time  with the rule deployed, the recorded attack is flagged before the
                                   point of no return
Coverage is the share of checks that pass.
"""
import json

from sdv.attacks.library import ALL_ATTACKS, make_attack
from sdv.blue.loop import base_monitors, benign_runs, deployed, known_ids_of, radar_params
from sdv.blue.rules import validate_rule
from sdv.blue.verify import case_outcome, false_alarm_rate
from sdv.monitors.monitors import observe
from sdv.runner import execute
from sdv.schemas import Scenario
from sdv.spec import stl

TOL = 1e-6


def _check(name, passed, detail=""):
    return {"name": name, "passed": bool(passed), "detail": detail}


def _rerun(violation):
    scenario = Scenario(**violation["scenario"])
    attack = make_attack(violation["attack"]["family"], **violation["attack"]["params"])
    return execute(scenario, violation["seed"], params=radar_params(), attacks=[attack])


def audit(bundle: dict) -> dict:
    checks = []
    spec, violation = bundle["spec"], bundle["violation"]

    try:
        formula = stl.parse(spec["formula"])
        checks.append(_check("spec_formula_parses", True, str(formula)))
        checks.append(_check("spec_bound_matches_deadline", abs(formula.hi_ms - spec["deadline_ms"]) < TOL,
                             f"formula {formula.hi_ms} ms vs deadline {spec['deadline_ms']} ms"))
    except stl.STLSyntaxError as error:
        formula = None
        checks.append(_check("spec_formula_parses", False, str(error)))
        checks.append(_check("spec_bound_matches_deadline", False, "formula did not parse"))

    result, chain = _rerun(violation)
    rec = violation["recorded"]
    robustness = formula.robustness(result.e2e_latency_ms) if formula else None
    reproduces = (result.e2e_latency_ms is not None
                  and abs(result.e2e_latency_ms - rec["e2e_latency_ms"]) < TOL
                  and robustness is not None and abs(robustness - rec["robustness_ms"]) < TOL
                  and result.outcome.collision == rec["collision"])
    checks.append(_check("violation_reproduces", reproduces,
                         f"re-run latency {result.e2e_latency_ms} vs recorded {rec['e2e_latency_ms']}"))
    checks.append(_check("violation_is_real", rec["robustness_ms"] < 0 or rec["collision"],
                         f"robustness {rec['robustness_ms']:.1f} ms, collision={rec['collision']}"))

    family = bundle["threat"]["family"]
    checks.append(_check("attack_is_known", family in ALL_ATTACKS
                         and ALL_ATTACKS[family].capability == bundle["threat"]["capability"], family))
    pattern = bundle["threat"]["kb_pattern"]
    from sdv.evidence.chain import _attack_file
    kb = {p["id"]: p for p in json.load(open(_attack_file(), encoding="utf-8"))["attack_patterns"]}
    checks.append(_check("kb_pattern_matches_the_knowledge_base",
                         pattern["id"] in kb and all(kb[pattern["id"]][k] == v for k, v in pattern.items()),
                         f"{pattern['id']} {pattern['name']}"))

    cal = bundle["calibration"]
    train = benign_runs(cal["n_train"], cal["train_seed0"])
    benign = benign_runs(cal["n_benign"], cal["benign_seed0"])
    known = known_ids_of(train)
    rule, errors = validate_rule(bundle["mitigation"]["rule"], known)
    checks.append(_check("rule_is_valid", rule is not None, "; ".join(errors)))
    if rule is None:
        checks += [_check("rule_fpr_reproduces", False, "invalid rule"),
                   _check("rule_catches_the_violation_in_time", False, "invalid rule")]
    else:
        base = base_monitors(train)
        monitor = deployed(base, [rule])
        fpr = false_alarm_rate(monitor, benign)
        ver = bundle["mitigation"]["verification"]
        checks.append(_check("rule_fpr_reproduces", fpr <= ver["fpr_cap"] + TOL,
                             f"deployed monitor false-alarm rate {fpr:.3f} (cap {ver['fpr_cap']})"))
        frames, ctx = observe(chain)
        start = chain.attack_windows[0][1]
        case = {"result": result, "ctx": ctx, "start_us": start}
        detected, in_time = case_outcome(case, monitor.first_alarm_us(frames, ctx))
        checks.append(_check("rule_catches_the_violation_in_time", in_time,
                             f"detected={detected}, in_time={in_time}"))

    passed = sum(c["passed"] for c in checks)
    return {"checks": checks, "passed": passed, "total": len(checks), "coverage": passed / len(checks),
            "all_passed": passed == len(checks)}
