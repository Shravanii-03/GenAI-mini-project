"""
tests/test_sdv_spec.py — STL fragment, validator, regex baseline, agent loop, scoring, benchmark.
(No API calls: the LLM is replaced by scripted replies.)
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.rag.kb import kb_ids
from sdv.rag.retrievers import BM25Retriever
from sdv.runner import run_once
from sdv.schemas import Scenario
from sdv.spec import stl
from sdv.spec.agent import build_prompt, extract_json, extract_spec
from sdv.spec.evaluate import aggregate, deadline_matches, load_benchmark, score
from sdv.spec.regex_baseline import regex_deadline
from sdv.spec.validator import validate

IDS = kb_ids()
GOOD = {"deadline_ms": 100, "unresolved": False, "component": "braking_system",
        "trigger": "obstacle_detected", "response": "brake_applied",
        "vss_signals": ["Vehicle.ADAS.ObstacleDetection.IsWarning"], "can_ids": ["0x1A0"],
        "formula": "G(obstacle_detected -> F[0,100 ms] brake_applied)"}


class TestSTL:

    def test_parse_and_roundtrip(self):
        f = stl.parse("G(obstacle_detected -> F[0,100 ms] brake_applied)")
        assert (f.trigger, f.response, f.lo_ms, f.hi_ms) == ("obstacle_detected", "brake_applied", 0, 100)
        assert stl.parse(str(f)) == f
        assert stl.format_formula("a", "b", 50) == "G(a -> F[0,50 ms] b)"

    @pytest.mark.parametrize("bad", ["", "F[0,100] x", "G(a -> b)", "G(A -> F[0,10 ms] b)",
                                     "G(a -> F[10,5 ms] b)", "G(a -> F[0,10 ms] b) & c"])
    def test_malformed_formulas_are_rejected(self, bad):
        with pytest.raises(stl.STLSyntaxError):
            stl.parse(bad)

    def test_robustness_is_the_slack_in_milliseconds(self):
        f = stl.parse("G(a -> F[0,100 ms] b)")
        assert f.robustness(60) == 40 and f.robustness(130) == -30
        assert f.robustness(None) == -math.inf and f.satisfied(100) and not f.satisfied(100.1)

    def test_lower_bound_makes_too_early_a_violation(self):
        f = stl.parse("G(a -> F[20,100 ms] b)")
        assert f.robustness(10) == -10 and f.robustness(60) == 40

    def test_robustness_matches_the_simulated_plant_margin(self):
        r = run_once(Scenario(v0_kmh=60, d0_m=30, cpu_load=0.4), seed=3)
        rho = stl.robustness_of_run("G(obstacle_detected -> F[0,100 ms] brake_applied)", r)
        assert rho == pytest.approx(100 - r.e2e_latency_ms)


class TestValidator:

    def test_a_correct_spec_has_no_errors(self):
        spec, errors = validate(GOOD, IDS)
        assert errors == [] and spec.deadline_ms == 100

    def test_invented_identifiers_are_reported_as_instructions(self):
        bad = dict(GOOD, vss_signals=["Vehicle.Brake.Emergency"], can_ids=["0x999"])
        _, errors = validate(bad, IDS)
        assert any("VSS signals" in e and "knowledge base" in e for e in errors)
        assert any("CAN IDs" in e for e in errors)

    def test_can_ids_are_case_normalised(self):
        spec, errors = validate(dict(GOOD, can_ids=["0x1a0"]), IDS)
        assert errors == [] and spec.can_ids == ["0x1A0"]

    def test_formula_must_agree_with_the_deadline(self):
        _, errors = validate(dict(GOOD, formula="G(a -> F[0,50 ms] b)"), IDS)
        assert any("do not match" in e for e in errors)

    def test_seconds_not_converted_is_caught(self):
        _, errors = validate(dict(GOOD, deadline_ms=0.1, formula="G(a -> F[0,0.1 ms] b)"), IDS)
        assert errors == []            # 0.1 ms is positive; plausibility only rejects <=0 or huge
        _, errors = validate(dict(GOOD, deadline_ms=100000, formula="G(a -> F[0,100000 ms] b)"), IDS)
        assert any("convert seconds" in e for e in errors)

    def test_vague_requirements_must_not_carry_a_deadline(self):
        _, errors = validate(dict(GOOD, unresolved=True), IDS)
        assert any("unresolved=true" in e for e in errors)

    def test_null_deadline_needs_null_formula(self):
        _, errors = validate(dict(GOOD, deadline_ms=None), IDS)
        assert any("formula must be null" in e for e in errors)
        spec, errors = validate(dict(GOOD, deadline_ms=None, formula=None, vss_signals=[], can_ids=[]), IDS)
        assert errors == []

    def test_schema_violations_are_reported(self):
        spec, errors = validate({"deadline_ms": "fast"}, IDS)
        assert spec is None and "schema" in errors[0]

    def test_unknown_component_is_rejected(self):
        _, errors = validate(dict(GOOD, component="engine"), IDS)
        assert any("component" in e for e in errors)


class TestRegexBaseline:

    @pytest.mark.parametrize("text,expected", [
        ("Brake within 100ms if obstacle detected.", 100.0),
        ("Warning within 0.2 s.", 200.0),
        ("At 80 km/h the brake shall engage within 120 ms.", 120.0),
        ("Heartbeat timeout: 500 msec.", 500.0),
        ("The airbag shall log events.", None),
    ])
    def test_extracts_explicit_values(self, text, expected):
        assert regex_deadline(text) == expected

    def test_cannot_do_arithmetic_or_words(self):
        assert regex_deadline("within five control cycles of 10 ms") == 10.0      # wrong: gold is 50
        assert regex_deadline("within a tenth of a second") is None              # misses entirely


class TestAgentLoop:

    def scripted(self, replies):
        it, seen = iter(replies), []
        def llm(prompt):
            seen.append(prompt)
            return next(it)
        llm.seen = seen
        return llm

    def test_json_is_extracted_from_fences_and_prose(self):
        assert extract_json('Sure!\n```json\n{"a": 1}\n```\nDone') == {"a": 1}
        assert extract_json("no json here") is None
        assert extract_json('{"a": {"b": 2}} trailing') == {"a": {"b": 2}}

    def test_a_valid_first_reply_needs_one_call(self):
        llm = self.scripted([json.dumps(GOOD)])
        r = extract_spec("Brake within 100 ms.", llm, ids=IDS)
        assert r.valid and r.llm_calls == 1 and r.repairs == 0

    def test_repair_loop_fixes_an_invented_signal(self):
        bad = json.dumps(dict(GOOD, vss_signals=["Vehicle.Invented.Signal"]))
        llm = self.scripted([bad, json.dumps(GOOD)])
        r = extract_spec("Brake within 100 ms.", llm, ids=IDS)
        assert r.valid and r.repairs == 1 and r.errors_initial and not r.errors_final
        assert "Vehicle.Invented.Signal" in llm.seen[1] and "validator found" in llm.seen[1]

    def test_validation_disabled_keeps_the_first_reply(self):
        bad = json.dumps(dict(GOOD, vss_signals=["Vehicle.Invented.Signal"]))
        llm = self.scripted([bad])
        r = extract_spec("x", llm, validate=False, ids=IDS)
        assert not r.valid and r.llm_calls == 1 and r.spec["vss_signals"] == ["Vehicle.Invented.Signal"]

    def test_repairs_are_bounded(self):
        bad = json.dumps(dict(GOOD, vss_signals=["Vehicle.Invented.Signal"]))
        llm = self.scripted([bad] * 5)
        r = extract_spec("x", llm, max_repairs=2, ids=IDS)
        assert not r.valid and r.llm_calls == 3 and r.repairs == 2

    def test_non_json_replies_are_handled(self):
        llm = self.scripted(["I cannot do that.", json.dumps(GOOD)])
        r = extract_spec("x", llm, ids=IDS)
        assert r.valid and r.repairs == 1 and r.errors_initial == ["the reply did not contain a JSON object"]

    def test_rag_prompt_lists_candidates_and_plain_prompt_does_not(self):
        retriever = BM25Retriever()
        llm = self.scripted([json.dumps(GOOD)])
        extract_spec("The brake pedal position shall be reported within 10 ms.", llm, retriever=retriever, ids=IDS)
        assert "Candidate VSS signals" in llm.seen[0] and "Vehicle.Chassis.Brake.PedalPosition" in llm.seen[0]
        assert "Candidate" not in build_prompt("x")


class TestScoring:

    def gold(self, **kw):
        base = {"id": "R1", "tags": ["explicit"], "deadline_ms": 100, "unresolved": False,
                "component": "braking_system", "vss_signals": ["Vehicle.ADAS.ObstacleDetection.IsWarning"],
                "can_ids": ["0x1A0"]}
        base.update(kw)
        return base

    def test_perfect_prediction(self):
        s = score(self.gold(), GOOD, IDS)
        assert s["exact"] and s["formula_ok"] and s["vss_fp"] == s["vss_fn"] == 0 and s["invalid_vss"] == 0

    def test_invented_signals_are_counted_as_invalid_and_false_positive(self):
        s = score(self.gold(), dict(GOOD, vss_signals=["Vehicle.Invented"], can_ids=["0x999"]), IDS)
        assert s["invalid_vss"] == 1 and s["invalid_can"] == 1 and s["vss_fp"] == 1 and s["vss_fn"] == 1

    def test_null_deadline_must_be_predicted_as_null(self):
        gold = self.gold(deadline_ms=None)
        assert score(gold, dict(GOOD, deadline_ms=None, formula=None), IDS)["deadline_ok"]
        assert not score(gold, GOOD, IDS)["deadline_ok"]

    def test_unparseable_output_scores_zero(self):
        s = score(self.gold(), None, IDS)
        assert not s["parsed"] and not s["exact"]

    def test_deadline_tolerance(self):
        assert deadline_matches(100.4, 100) and not deadline_matches(101, 100)
        assert deadline_matches(None, None) and not deadline_matches(None, 100)

    def test_aggregate_micro_f1_and_intervals(self):
        rows = [score(self.gold(), GOOD, IDS), score(self.gold(), dict(GOOD, deadline_ms=50,
                formula="G(a -> F[0,50 ms] b)"), IDS)]
        agg = aggregate(rows)
        assert agg["deadline_ok"] == 0.5 and agg["vss_f1"] == 1.0
        assert agg["deadline_ok_ci"][0] < 0.5 < agg["deadline_ok_ci"][1]


class TestBenchmark:

    def test_size_categories_and_labels(self):
        bench = load_benchmark()
        assert len(bench) == 120 and len({b["id"] for b in bench}) == 120
        assert {b["tags"][0] for b in bench} == {"explicit", "units", "distractor", "multi_clause",
                                                "no_deadline", "vague", "derived", "format"}
        for b in bench:
            assert set(b["vss_signals"]) <= IDS["vss"] and set(b["can_ids"]) <= IDS["can"]
            assert (b["deadline_ms"] is None) or b["deadline_ms"] > 0
            assert not (b["unresolved"] and b["deadline_ms"] is not None)

    def test_regex_baseline_is_good_on_explicit_and_bad_on_derived(self):
        bench = load_benchmark()
        def acc(tag):
            rows = [b for b in bench if b["tags"][0] == tag]
            return sum(deadline_matches(regex_deadline(b["text"]), b["deadline_ms"]) for b in rows) / len(rows)
        assert acc("explicit") > 0.9 and acc("derived") < 0.6 and acc("vague") == 1.0
