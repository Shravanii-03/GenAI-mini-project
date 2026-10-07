"""
tests/test_sdv_evidence.py — evidence bundle, auditor (including tamper detection) and rendering.
"""
import copy
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.blue.loop import base_monitors, benign_runs, collect_cases, deployed, known_ids_of
from sdv.blue.verify import verify_rule
from sdv.evidence.audit import audit
from sdv.evidence.chain import build_bundle, kb_pattern_for
from sdv.evidence.render import render_markdown
from sdv.spec import stl

XCHK = {"type": "cross_check", "id_a": "0x2A0", "id_b": "0x2B0", "field": "distance_m",
        "tol": 2.0, "max_skew_ms": 15.0}
CAL = {"train_seed0": 940000, "n_train": 40, "benign_seed0": 950000, "n_benign": 40, "fpr_cap": 0.02}
SPEC = {"deadline_ms": 100.0, "formula": "G(obstacle_detected -> F[0,100 ms] brake_applied)",
        "trigger": "obstacle_detected", "response": "brake_applied", "component": "braking_system"}
REQ = {"id": "R-test", "text": "Brake within 100 ms if an obstacle is detected.", "method": "test"}


@pytest.fixture(scope="module")
def bundle():
    train = benign_runs(CAL["n_train"], CAL["train_seed0"])
    benign = benign_runs(CAL["n_benign"], CAL["benign_seed0"])
    base = base_monitors(train)
    _, missed, _ = collect_cases(deployed(base, []), ["masquerade"], 40, random.Random(5))
    assert missed, "the test needs at least one missed masquerade hazard"
    verdict = verify_rule(XCHK, benign, missed, known_ids_of(train), CAL["fpr_cap"])
    assert verdict["ok"]
    return build_bundle(REQ, SPEC, missed[0], verdict, CAL, residual={"dual_masquerade": "not coverable"})


class TestBundle:

    def test_it_links_requirement_trace_threat_and_mitigation(self, bundle):
        assert set(bundle) >= {"requirement", "spec", "violation", "threat", "mitigation", "calibration"}
        assert bundle["violation"]["attack"]["family"] == "masquerade"
        assert bundle["mitigation"]["rule"]["type"] == "cross_check"

    def test_the_recorded_robustness_is_the_stl_value_of_the_recorded_latency(self, bundle):
        rec = bundle["violation"]["recorded"]
        assert rec["robustness_ms"] == pytest.approx(stl.parse(SPEC["formula"]).robustness(rec["e2e_latency_ms"]))

    def test_the_threat_cites_the_declared_pattern_and_records_what_retrieval_suggested(self, bundle):
        pattern = bundle["threat"]["kb_pattern"]
        assert pattern["id"] == "ATK-002" and "redundant sensing" in pattern["mitigation"]
        assert kb_pattern_for("masquerade")["id"] == pattern["id"]
        sug = pattern["retrieval_suggestion"]
        assert set(sug) == {"id", "name", "agrees"} and sug["agrees"] == (sug["id"] == pattern["id"])

    def test_every_family_has_a_declared_pattern_that_exists_in_the_kb(self):
        from sdv.attacks.library import ALL_ATTACKS, KB_PATTERN_FOR
        from sdv.rag.kb import kb_ids
        assert set(KB_PATTERN_FOR) == set(ALL_ATTACKS)
        assert set(KB_PATTERN_FOR.values()) <= kb_ids()["attack"]


class TestAudit:

    def test_an_honest_bundle_passes_every_check(self, bundle):
        report = audit(bundle)
        assert report["all_passed"], [c for c in report["checks"] if not c["passed"]]
        assert report["total"] == 10 and report["coverage"] == 1.0

    def test_a_falsified_latency_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["violation"]["recorded"]["e2e_latency_ms"] += 5.0
        failed = {c["name"] for c in audit(bad)["checks"] if not c["passed"]}
        assert "violation_reproduces" in failed

    def test_a_falsified_collision_claim_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["violation"]["recorded"]["collision"] = not bad["violation"]["recorded"]["collision"]
        assert "violation_reproduces" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_changed_attack_parameters_no_longer_reproduce(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["violation"]["attack"]["params"]["bias_m"] = 1.0
        assert "violation_reproduces" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_a_formula_that_disagrees_with_the_deadline_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["spec"]["formula"] = "G(a -> F[0,50 ms] b)"
        assert "spec_bound_matches_deadline" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_an_unparseable_formula_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["spec"]["formula"] = "always brake"
        failed = {c["name"] for c in audit(bad)["checks"] if not c["passed"]}
        assert {"spec_formula_parses", "spec_bound_matches_deadline"} <= failed

    def test_a_tampered_knowledge_base_citation_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["threat"]["kb_pattern"]["tara_risk_score"] = 0.01
        assert "kb_pattern_matches_the_knowledge_base" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_citing_the_wrong_but_real_pattern_is_caught(self, bundle):
        """ATK-007 exists in the KB with these exact fields, but it is not the pattern for masquerade."""
        import json
        from sdv.evidence.chain import _attack_file
        raw = next(p for p in json.load(open(_attack_file(), encoding="utf-8"))["attack_patterns"]
                   if p["id"] == "ATK-007")
        bad = copy.deepcopy(bundle)
        bad["threat"]["kb_pattern"] = {k: raw[k] for k in ("id", "name", "severity", "likelihood",
                                                          "tara_risk_score", "iso_reference", "mitigation")}
        failed = {c["name"] for c in audit(bad)["checks"] if not c["passed"]}
        assert failed == {"threat_mapping_is_declared"}

    def test_a_rule_that_alarms_on_benign_traffic_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["mitigation"]["rule"] = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}
        failed = {c["name"] for c in audit(bad)["checks"] if not c["passed"]}
        assert "rule_fpr_reproduces" in failed

    def test_a_rule_that_does_not_cover_the_violation_is_caught(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["mitigation"]["rule"] = {"type": "range", "id": "0x2A0", "field": "distance_m", "lo": -5, "hi": 300}
        assert "rule_catches_the_violation_in_time" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_an_invalid_rule_fails_cleanly(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["mitigation"]["rule"] = {"type": "cross_check", "id_a": "0x999", "id_b": "0x2B0",
                                     "field": "distance_m", "tol": 1, "max_skew_ms": 5}
        failed = {c["name"] for c in audit(bad)["checks"] if not c["passed"]}
        assert {"rule_is_valid", "rule_fpr_reproduces", "rule_catches_the_violation_in_time"} <= failed

    def test_the_audit_is_deterministic(self, bundle):
        assert audit(bundle) == audit(bundle)


class TestRender:

    def test_markdown_shows_every_link_and_the_audit_result(self, bundle):
        text = render_markdown(bundle, audit(bundle))
        for needle in ("G1.", "S1. Specification", "S2. Counter-example", "S3. Threat", "S4. Mitigation",
                       "Residual risk", "dual_masquerade", "10/10 checks re-verified", "[PASS]", "not a certified safety case"):
            assert needle in text

    def test_failures_are_visible_in_the_document(self, bundle):
        bad = copy.deepcopy(bundle)
        bad["violation"]["recorded"]["e2e_latency_ms"] += 5.0
        assert "[FAIL]" in render_markdown(bad, audit(bad))

    def test_it_renders_without_an_audit(self, bundle):
        assert "Audit:" not in render_markdown(bundle)


class TestFailoverEvidence:

    @pytest.fixture(scope="class")
    def with_failover(self, bundle):
        from sdv.evidence.chain import failover_record
        b = copy.deepcopy(bundle)
        case = {"scenario": b["violation"]["scenario"], "family": b["violation"]["attack"]["family"],
                "theta": b["violation"]["attack"]["params"], "seed": b["violation"]["seed"]}
        b["failover"] = failover_record(case)
        return b

    def test_an_honest_failover_record_passes_and_the_masquerade_is_prevented(self, with_failover):
        report = audit(with_failover)
        assert report["all_passed"] and report["total"] == 12
        assert with_failover["failover"]["effective"] is True

    def test_a_falsified_failover_outcome_is_caught(self, with_failover):
        bad = copy.deepcopy(with_failover)
        bad["failover"]["e2e_latency_ms"] += 5.0
        assert "failover_reproduces" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_a_falsified_safety_claim_is_caught(self, with_failover):
        bad = copy.deepcopy(with_failover)
        bad["failover"]["bound_proves_safe"] = not bad["failover"]["bound_proves_safe"]
        assert "failover_bound_is_sound" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_a_tampered_bound_is_caught(self, with_failover):
        bad = copy.deepcopy(with_failover)
        bad["failover"]["latency_bound_ms"] *= 0.5
        assert "failover_bound_is_sound" in {c["name"] for c in audit(bad)["checks"] if not c["passed"]}

    def test_rendering_shows_the_failover_section(self, with_failover):
        text = render_markdown(with_failover, audit(with_failover))
        assert "S5. Failover to the redundant sensor" in text and "12/12 checks re-verified" in text

    def test_a_dual_sensor_attack_is_recorded_as_not_prevented(self):
        from sdv.evidence.chain import failover_record
        from sdv.schemas import Scenario
        scen = Scenario(v0_kmh=60, d0_m=22, cpu_load=0.3)
        rec = failover_record({"scenario": scen.model_dump(), "family": "dual_masquerade", "seed": 1,
                               "theta": {"bias_m": 40.0, "duration_ms": 800.0, "start_offset_ms": 0.0}})
        assert rec["effective"] is False and rec["bound_proves_safe"] is False
