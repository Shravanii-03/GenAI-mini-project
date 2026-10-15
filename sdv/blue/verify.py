"""
Deterministic verification of monitor rules.

A rule is accepted only if it (1) validates against the language bounds, (2) raises false
alarms on at most `fpr_cap` of held-out benign runs, and (3) turns at least one missed hazard
into an in-time detection. Nothing here calls a model, so an LLM-proposed rule earns its place
exactly like a hand-written or enumerated one.

A "case" is one missed attack: frames/ctx (bus-visible), the run result, the attack start and
window, and the alarm the current monitors raised (None if they stayed silent).
"""
from sdv.blue.rules import RuleMonitor, validate_rule
from sdv.metrics.detection_margin import credited_alarm_us, detection_margin_ms
from sdv.search.problem import RESPONSE_MS


def _earliest(*alarms):
    present = [a for a in alarms if a is not None]
    return min(present) if present else None


def case_outcome(case, alarm_us):
    """(detected, in_time) for a case given the alarm time of whatever monitors are deployed."""
    credited = credited_alarm_us(alarm_us, case["start_us"])
    margin = detection_margin_ms(case["result"], credited, case["ctx"].t_appear_us, RESPONSE_MS)
    return credited is not None, bool(margin is not None and margin > 0)


def false_alarm_rate(monitor, benign_obs):
    if not benign_obs:
        return float("nan")
    return sum(monitor.first_alarm_us(frames, ctx) is not None for frames, ctx in benign_obs) / len(benign_obs)


def verify_rule(rule: dict, benign_obs, cases, known_ids, fpr_cap: float = 0.02):
    """Full verdict for one proposed rule."""
    normalised, errors = validate_rule(rule, known_ids)
    verdict = {"rule": normalised or rule, "errors": errors, "ok": False, "fpr": None,
               "new_detections": 0, "new_timely": 0}
    if normalised is None:
        return verdict
    monitor = RuleMonitor(normalised)
    verdict["fpr"] = false_alarm_rate(monitor, benign_obs)
    for case in cases:
        rule_alarm = monitor.first_alarm_us(case["frames"], case["ctx"])
        before = case_outcome(case, case["base_alarm"])
        after = case_outcome(case, _earliest(case["base_alarm"], rule_alarm))
        verdict["new_detections"] += after[0] and not before[0]
        verdict["new_timely"] += after[1] and not before[1]
    if verdict["fpr"] > fpr_cap:
        verdict["errors"] = [f"false-alarm rate {verdict['fpr']:.2f} on benign runs exceeds the cap {fpr_cap:.2f}; "
                             "loosen the threshold"]
    elif verdict["new_timely"] < 1:
        verdict["errors"] = ["the rule does not turn any missed hazard into an in-time detection"]
    else:
        verdict["ok"] = True
    return verdict


def adopt_rule(rule: dict, cases):
    """Update each case's current alarm after a rule has been accepted."""
    monitor = RuleMonitor(rule)
    for case in cases:
        case["base_alarm"] = _earliest(case["base_alarm"], monitor.first_alarm_us(case["frames"], case["ctx"]))


def uncovered(cases):
    """Cases still missed in time by the deployed monitors."""
    return [c for c in cases if not case_outcome(c, c["base_alarm"])[1]]
