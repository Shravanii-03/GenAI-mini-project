"""
tests/test_sdv_pipeline.py — the end-to-end pipeline and its command line (no API calls).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.pipeline import extract_spec, format_summary, main, run_pipeline

REQ = "Braking must start within 0.1 seconds of an obstacle being detected."
XCHK = {"type": "cross_check", "id_a": "0x2A0", "id_b": "0x2B0", "field": "distance_m",
        "tol": 2.0, "max_skew_ms": 15.0}


def scripted(*replies):
    seen, it = [], iter(replies)

    def llm(prompt):
        seen.append(prompt)
        return next(it)
    llm.seen = seen
    return llm


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("pipeline")
    return run_pipeline(REQ, seed=1, n_per_family=30, blue="enumerate", out_dir=str(out), assess_n=16), out


class TestSpecStep:

    def test_regex_fallback_converts_units(self):
        spec, method = extract_spec(REQ)
        assert spec["deadline_ms"] == 100.0 and method == "regex baseline"
        assert spec["formula"] == "G(obstacle_detected -> F[0,100 ms] brake_applied)"

    def test_a_requirement_without_a_number_stops_the_pipeline(self):
        assert extract_spec("The brake shall act promptly.")[0] is None
        assert "error" in run_pipeline("The brake shall act promptly.", n_per_family=5, assess_defences=False)

    def test_the_llm_agent_is_used_when_given(self):
        reply = json.dumps({"deadline_ms": 150, "unresolved": False, "component": "braking_system",
                            "trigger": "obstacle_detected", "response": "brake_applied", "vss_signals": [],
                            "can_ids": [], "formula": "G(obstacle_detected -> F[0,150 ms] brake_applied)"})
        spec, method = extract_spec("Brake within 150 ms.", scripted(reply))
        assert spec["deadline_ms"] == 150 and "LLM spec agent" in method

    def test_an_unusable_llm_reply_falls_back_to_the_regex(self):
        spec, method = extract_spec("Brake within 150 ms.", scripted(*(["nonsense"] * 5)))
        assert spec["deadline_ms"] == 150.0 and method == "regex baseline"


class TestPipelineRun:

    def test_the_requirement_deadline_reaches_the_formula(self, run):
        summary, _ = run
        assert summary["spec"]["deadline_ms"] == 100.0

    def test_red_team_finds_missed_hazards_in_two_families_only(self, run):
        summary, _ = run
        assert summary["hazards_round0"] > 20 and summary["missed_round0"] > 5

    def test_blue_team_adds_a_verified_cross_check_rule(self, run):
        summary, _ = run
        assert [r["type"] for r in summary["rules"]] == ["cross_check"]
        assert summary["in_time_after"] > summary["in_time_before"] + 0.1
        assert summary["fpr_after"] <= 0.05

    def test_the_dual_sensor_attacker_remains_as_residual_risk(self, run):
        summary, _ = run
        assert "dual_masquerade" in summary["round1_missed"]
        assert "masquerade" not in summary["round1_missed"] or summary["round1_missed"]["masquerade"] < 3
        assert "dual_masquerade" in summary["residual_risk"]

    def test_the_evidence_bundle_is_written_and_passes_its_audit(self, run):
        summary, out = run
        assert summary["evidence"]["all_passed"] and summary["evidence"]["audit_total"] == 20
        for name in ("pipeline_summary.json", "evidence_bundle.json", "evidence.md"):
            assert (out / name).exists()
        text = (out / "evidence.md").read_text(encoding="utf-8")
        assert "20/20 checks re-verified" in text and "dual_masquerade" in text
        assert json.loads((out / "evidence_bundle.json").read_text())["spec"]["deadline_ms"] == 100.0

    def test_the_summary_text_mentions_every_stage(self, run):
        text = format_summary(run[0])
        for needle in ("requirement", "spec", "red round 0", "blue (enumerate)", "residual risk", "evidence"):
            assert needle in text


class TestBlueChoices:

    def test_no_blue_means_no_rules_and_no_evidence(self):
        s = run_pipeline(REQ, seed=2, n_per_family=15, blue="none", assess_defences=False)
        assert s["rules"] == [] and s["evidence"] is None
        assert s["in_time_after"] == pytest.approx(s["in_time_before"])

    def test_the_llm_arm_needs_an_llm(self):
        with pytest.raises(ValueError):
            run_pipeline(REQ, n_per_family=5, blue="llm", assess_defences=False)

    def test_an_unknown_choice_is_rejected(self):
        with pytest.raises(ValueError):
            run_pipeline(REQ, n_per_family=5, blue="magic", assess_defences=False)

    def test_the_llm_arm_is_verified_like_the_others(self):
        jumpy = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}
        llm = scripted(*([json.dumps({"rules": [jumpy, XCHK]})] * 3))
        s = run_pipeline(REQ, seed=1, n_per_family=30, blue="llm", blue_llm=llm, assess_defences=False)
        assert [r["type"] for r in s["rules"]] == ["cross_check"]      # the unsafe jump rule was rejected

    def test_random_proposals_also_work(self):
        s = run_pipeline(REQ, seed=1, n_per_family=30, blue="random", assess_defences=False)
        assert s["blue_cost"] == {"proposals": 9}


class TestCommandLine:

    def test_main_runs_end_to_end_and_writes_files(self, tmp_path, capsys):
        code = main(["--requirement", REQ, "--n", "12", "--blue", "enumerate", "--assess-n", "6", "--out", str(tmp_path / "o")])
        printed = capsys.readouterr().out
        assert code == 0 and "spec" in printed and "files written to" in printed
        assert (tmp_path / "o" / "pipeline_summary.json").exists()

    def test_main_reports_a_missing_deadline(self, capsys):
        assert main(["--requirement", "Brake promptly.", "--n", "5", "--no-assess"]) == 1
        assert "pipeline stopped" in capsys.readouterr().out


class TestNewStages:

    def test_requirement_conformance_is_reported_and_a_100_ms_deadline_is_not_provable(self, run):
        c = run[0]["conformance"]
        assert c["deadline_ms"] == 100.0 and set(c["configs"]) == {"baseline", "all defences"}
        for cfg in c["configs"].values():
            assert cfg["bound_max_ms"] > 100.0 and cfg["verdict"] != "proven"
            assert cfg["smallest_provable_deadline_ms"] == cfg["bound_max_ms"]

    def test_defence_assessment_is_reported_with_the_open_cases(self, run):
        a = run[0]["defence_assessment"]
        assert a["n_per_variant"] == 16 and a["bound_violations"] == 0
        assert {"dos_flood (safety-bus node)", "dual_masquerade (holds key)"} <= set(a["open"])
        rec = {r["variant"]: r["config"] for r in a["recommendation"]}
        assert rec["masquerade"] in ("radar_or", "+guard", "+auth", "+guard+auth")
        assert rec["dos_flood"] in ("+guard", "+guard+auth")

    def test_assessment_text_and_file(self, run):
        summary, out = run
        text = format_summary(summary)
        assert "requirement conformance" in text and "defence assessment" in text and "open after every defence" in text
        assert "defence assessment" in (out / "assessment.md").read_text(encoding="utf-8")

    def test_assessment_can_be_skipped(self):
        s = run_pipeline(REQ, seed=2, n_per_family=10, blue="none", assess_defences=False)
        assert s["defence_assessment"] is None and s["conformance"]["configs"]

    def test_a_calibrated_plant_profile_is_applied_reported_and_audited(self):
        profile = {"name": "weak-brakes", "decel_ms2": 5.31, "brake_ramp_ms": 50}
        s = run_pipeline(REQ, seed=1, n_per_family=30, blue="enumerate", plant_profile=profile, assess_defences=False)
        assert s["plant_profile"]["name"] == "weak-brakes"
        assert "weak-brakes" in format_summary(s)
        if s["evidence"]:
            assert s["evidence"]["all_passed"]

    def test_the_bundled_carla_profile_loads(self):
        from sdv.plant.profile import load_profile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        profile = load_profile(os.path.join(root, "experiments", "profiles", "carla_model3.json"))
        assert profile["decel_ms2"] == 5.31 and "run 4" in profile["source"]

    def test_the_deployment_check_keeps_the_deployed_false_alarm_rate_under_the_cap(self):
        # regression: with 20 samples per family the verified rule used to push the DEPLOYED monitor over the cap
        s = run_pipeline(REQ, seed=1, n_per_family=20, blue="enumerate", assess_defences=False)
        if s["evidence"]:
            assert s["evidence"]["all_passed"]
        assert len(s["rules"]) + len(s["rules_dropped_by_deployment_check"]) <= 3
