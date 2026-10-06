"""
tests/test_sdv_blue.py — rule language, verifier, enumerator and the red/blue machinery.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.blue.loop import (
    base_monitors, benign_runs, collect_cases, deployed, known_ids_of, refresh_alarms, timely_rate,
)
import json

from sdv.blue.agent import blue_step_llm, build_prompt, parse_rules, propose_rules
from sdv.blue.rules import RuleMonitor, compile_rule, normalise_id, validate_rule
from sdv.blue.summary import describe, numeric_ids
from sdv.blue.synth import candidates, enumerate_step, random_step
from sdv.blue.verify import false_alarm_rate, uncovered, verify_rule
from sdv.monitors.monitors import Context, Observed

KNOWN = [0x2A0, 0x2B0, 0x1A0]
CTX = Context(end_us=2_000_000, t_appear_us=500_000, bitrate=500_000)
XCHK = {"type": "cross_check", "id_a": "0x2A0", "id_b": "0x2B0", "field": "distance_m",
        "tol": 2.0, "max_skew_ms": 15.0}


def frame(t_us, can_id, **data):
    return Observed(t_us, can_id, 8, data)


class TestIds:

    def test_ids_are_normalised_from_ints_and_strings(self):
        assert normalise_id(672) == normalise_id("0x2a0") == normalise_id("0x2A0") == "0x2A0"


class TestValidation:

    def test_a_good_rule_validates(self):
        rule, errors = validate_rule(XCHK, KNOWN)
        assert errors == [] and rule["tol"] == 2.0

    @pytest.mark.parametrize("change,fragment", [
        ({"type": "magic"}, "unknown rule type"),
        ({"id_a": "0x999"}, "not a CAN ID seen on the bus"),
        ({"id_b": "0x2A0"}, "two different IDs"),
        ({"field": "colour"}, "not allowed"),
        ({"tol": 500}, "outside the allowed range"),
        ({"tol": "big"}, "must be a number"),
        ({"surprise": 1}, "unknown keys"),
    ])
    def test_bad_rules_get_instruction_style_errors(self, change, fragment):
        rule, errors = validate_rule({**XCHK, **change}, KNOWN)
        assert rule is None and any(fragment in e for e in errors)

    def test_range_needs_ordered_bounds(self):
        _, errors = validate_rule({"type": "range", "id": "0x2A0", "field": "distance_m", "lo": 10, "hi": 5}, KNOWN)
        assert any("lo < hi" in e for e in errors)

    def test_non_objects_are_rejected(self):
        assert validate_rule("cross_check", KNOWN)[0] is None

    def test_compile_returns_a_monitor_or_errors(self):
        monitor, errors = compile_rule(XCHK, KNOWN)
        assert isinstance(monitor, RuleMonitor) and errors == []
        assert compile_rule({"type": "x"}, KNOWN)[0] is None


class TestRuleSemantics:

    def test_cross_check_alarms_on_disagreement_only(self):
        agree = [frame(0, 0x2A0, distance_m=20.0), frame(1000, 0x2B0, distance_m=20.5)]
        differ = [frame(0, 0x2A0, distance_m=20.0), frame(1000, 0x2B0, distance_m=30.0)]
        m = RuleMonitor(validate_rule(XCHK, KNOWN)[0])
        assert m.first_alarm_us(agree, CTX) is None
        assert m.first_alarm_us(differ, CTX) == 1000

    def test_cross_check_ignores_frames_too_far_apart_in_time(self):
        far = [frame(0, 0x2A0, distance_m=20.0), frame(200_000, 0x2B0, distance_m=90.0)]
        assert RuleMonitor(validate_rule(XCHK, KNOWN)[0]).first_alarm_us(far, CTX) is None

    def test_jump_detects_a_step(self):
        rule = validate_rule({"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 2.0}, KNOWN)[0]
        smooth = [frame(i * 10_000, 0x2A0, distance_m=30 - 0.17 * i) for i in range(10)]
        stepped = smooth[:5] + [frame(50_000 + i * 10_000, 0x2A0, distance_m=45 - 0.17 * i) for i in range(5)]
        assert RuleMonitor(rule).first_alarm_us(smooth, CTX) is None
        assert RuleMonitor(rule).first_alarm_us(stepped, CTX) == 50_000

    def test_drift_detects_a_rising_distance_to_an_approaching_obstacle(self):
        rule = validate_rule({"type": "drift", "id": "0x2A0", "field": "distance_m",
                              "window": 5, "slack_m": 0.5}, KNOWN)[0]
        falling = [frame(i * 10_000, 0x2A0, distance_m=30 - 0.17 * i) for i in range(20)]
        rising = [frame(i * 10_000, 0x2A0, distance_m=30 + 0.2 * i) for i in range(20)]
        assert RuleMonitor(rule).first_alarm_us(falling, CTX) is None
        assert RuleMonitor(rule).first_alarm_us(rising, CTX) == 5 * 10_000

    def test_range_alarms_outside_the_interval(self):
        rule = validate_rule({"type": "range", "id": "0x2A0", "field": "distance_m", "lo": 0, "hi": 100}, KNOWN)[0]
        assert RuleMonitor(rule).first_alarm_us([frame(5, 0x2A0, distance_m=50.0)], CTX) is None
        assert RuleMonitor(rule).first_alarm_us([frame(5, 0x2A0, distance_m=150.0)], CTX) == 5

    def test_frames_without_the_field_are_ignored(self):
        assert RuleMonitor(validate_rule(XCHK, KNOWN)[0]).first_alarm_us(
            [frame(0, 0x2A0, distance_m=None), frame(5, 0x2B0, distance_m=None)], CTX) is None


@pytest.fixture(scope="module")
def world():
    """Small but real: benign calibration/validation runs and missed hazards from the two masquerades."""
    train = benign_runs(40, 920000)
    valid = benign_runs(40, 930000)
    base = base_monitors(train)
    monitor = deployed(base, [])
    _, missed, _ = collect_cases(monitor, ["masquerade", "dual_masquerade"], 40, random.Random(7))
    return {"train": train, "valid": valid, "base": base, "monitor": monitor, "missed": missed,
            "known": known_ids_of(train)}


class TestRedBlueOnSimulatedData:

    def test_the_baseline_monitors_miss_both_masquerades(self, world):
        families = {c["family"] for c in world["missed"]}
        assert families == {"masquerade", "dual_masquerade"}

    def test_cross_check_rule_is_verified_and_catches_only_the_single_masquerade(self, world):
        single = [c for c in world["missed"] if c["family"] == "masquerade"]
        dual = [c for c in world["missed"] if c["family"] == "dual_masquerade"]
        rule = {**XCHK, "tol": 2.0}
        v = verify_rule(rule, world["valid"], single, world["known"])
        assert v["ok"] and v["fpr"] == 0.0 and v["new_timely"] >= 1
        assert verify_rule(rule, world["valid"], dual, world["known"])["new_timely"] == 0

    def test_rules_that_alarm_on_benign_traffic_are_rejected(self, world):
        jumpy = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}
        v = verify_rule(jumpy, world["valid"], world["missed"], world["known"], fpr_cap=0.02)
        assert not v["ok"] and any("false-alarm rate" in e for e in v["errors"])

    def test_a_rule_that_helps_nothing_is_rejected(self, world):
        useless = {"type": "range", "id": "0x2A0", "field": "distance_m", "lo": -5, "hi": 300}
        v = verify_rule(useless, world["valid"], world["missed"], world["known"])
        assert not v["ok"] and any("in-time detection" in e for e in v["errors"])

    def test_enumeration_finds_the_cross_check_and_stops_at_the_dual_attacker(self, world):
        cases = [dict(c) for c in world["missed"]]
        accepted, evaluated = enumerate_step(world["valid"], cases, world["known"], 0.02, 3)
        assert accepted and accepted[0]["rule"]["type"] == "cross_check" and evaluated > 50
        left = uncovered(cases)
        assert left and all(c["family"] == "dual_masquerade" for c in left)

    def test_deploying_the_rule_raises_the_in_time_rate_without_false_alarms(self, world):
        hazards = [dict(c) for c in world["missed"]]
        before = timely_rate(hazards)
        monitor = deployed(world["base"], [XCHK])
        refresh_alarms(hazards, monitor)
        assert timely_rate(hazards) > before
        assert false_alarm_rate(monitor, world["valid"]) <= 0.05

    def test_candidate_grid_is_built_from_the_signals_seen_in_benign_traffic(self, world):
        ids = numeric_ids(world["train"])
        assert ids == [0x2A0, 0x2B0]
        assert len(candidates(world["train"])) == 18 + 2 * (5 + 12)

    def test_evidence_summary_is_per_family_and_does_not_name_a_fix(self, world):
        text = describe(world["valid"], world["missed"])
        assert "During masquerade attack windows" in text and "During dual_masquerade attack windows" in text
        assert "cross_check" not in text


def scripted(*replies):
    seen, it = [], iter(replies)

    def llm(prompt):
        seen.append(prompt)
        return next(it)
    llm.seen = seen
    return llm


class TestBlueAgent:

    def test_prompt_contains_the_language_and_the_evidence_but_no_answer(self):
        prompt = build_prompt("EVIDENCE-TEXT", "- earlier rule: rejected")
        assert "cross_check" in prompt and "EVIDENCE-TEXT" in prompt and "earlier rule" in prompt
        assert "0x2A0" not in prompt            # the prompt does not name specific IDs by itself

    def test_rules_are_parsed_from_prose_and_garbage_gives_nothing(self):
        assert parse_rules('Sure: {"rules": [{"type": "range"}]} done') == [{"type": "range"}]
        assert parse_rules("I cannot help") == [] and parse_rules('{"rules": "x"}') == []

    def test_invalid_rules_trigger_a_repair_with_the_errors(self):
        bad = json.dumps({"rules": [{**XCHK, "id_a": "0x999"}]})
        good = json.dumps({"rules": [XCHK]})
        llm = scripted(bad, good)
        rules, calls, errors = propose_rules(llm, "evidence", KNOWN)
        assert len(rules) == 1 and calls == 2 and errors
        assert "not a CAN ID seen on the bus" in llm.seen[1]

    def test_repairs_are_bounded(self):
        llm = scripted(*(["nonsense"] * 5))
        rules, calls, _ = propose_rules(llm, "evidence", KNOWN, max_repairs=2)
        assert rules == [] and calls == 3

    def test_only_verified_rules_are_adopted(self, world):
        cases = [dict(c) for c in world["missed"]]
        jumpy = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}   # fires on benign
        llm = scripted(json.dumps({"rules": [jumpy, XCHK]}))
        accepted, stats = blue_step_llm(llm, world["valid"], cases, world["known"], attempts=1)
        assert [a["rule"]["type"] for a in accepted] == ["cross_check"]
        assert stats["proposals"] == 2 and stats["rejected_proposals"] == 1

    def test_rejection_reasons_are_fed_back_in_the_next_attempt(self, world):
        cases = [dict(c) for c in world["missed"] if c["family"] == "masquerade"]
        jumpy = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}
        llm = scripted(json.dumps({"rules": [jumpy]}), json.dumps({"rules": [XCHK]}))
        accepted, stats = blue_step_llm(llm, world["valid"], cases, world["known"], attempts=3)
        assert len(accepted) == 1 and stats["attempts"] == 2
        assert "false-alarm rate" in llm.seen[1]

    def test_the_loop_stops_when_nothing_is_left_to_fix(self, world):
        single = [dict(c) for c in world["missed"] if c["family"] == "masquerade"]
        llm = scripted(json.dumps({"rules": [XCHK]}))
        accepted, stats = blue_step_llm(llm, world["valid"], single, world["known"], attempts=3)
        assert len(accepted) == 1 and stats["attempts"] == 1 and not uncovered(single)

    def test_the_dual_attacker_defeats_every_proposal(self, world):
        dual = [dict(c) for c in world["missed"] if c["family"] == "dual_masquerade"]
        llm = scripted(*([json.dumps({"rules": [XCHK]})] * 3))
        accepted, stats = blue_step_llm(llm, world["valid"], dual, world["known"], attempts=3)
        assert accepted == [] and stats["rejected_proposals"] == 3 and uncovered(dual)


class TestRandomBaseline:

    def test_random_proposals_pass_through_the_same_verifier(self, world):
        cases = [dict(c) for c in world["missed"]]
        accepted, budget = random_step(world["valid"], cases, world["known"], random.Random(0), proposals=40)
        assert budget == 40
        for a in accepted:
            assert a["fpr"] <= 0.02 and a["new_timely"] >= 1

    def test_random_search_cannot_fix_the_dual_attacker_either(self, world):
        dual = [dict(c) for c in world["missed"] if c["family"] == "dual_masquerade"]
        accepted, _ = random_step(world["valid"], dual, world["known"], random.Random(1), proposals=60)
        assert accepted == []
