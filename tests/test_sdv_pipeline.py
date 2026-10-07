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
    return run_pipeline(REQ, seed=1, n_per_family=30, blue="enumerate", out_dir=str(out)), out


class TestSpecStep:

    def test_regex_fallback_converts_units(self):
        spec, method = extract_spec(REQ)
        assert spec["deadline_ms"] == 100.0 and method == "regex baseline"
        assert spec["formula"] == "G(obstacle_detected -> F[0,100 ms] brake_applied)"

    def test_a_requirement_without_a_number_stops_the_pipeline(self):
        assert extract_spec("The brake shall act promptly.")[0] is None
        assert "error" in run_pipeline("The brake shall act promptly.", n_per_family=5)

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
        assert summary["evidence"]["all_passed"] and summary["evidence"]["audit_total"] == 12
        for name in ("pipeline_summary.json", "evidence_bundle.json", "evidence.md"):
            assert (out / name).exists()
        text = (out / "evidence.md").read_text(encoding="utf-8")
        assert "12/12 checks re-verified" in text and "dual_masquerade" in text
        assert json.loads((out / "evidence_bundle.json").read_text())["spec"]["deadline_ms"] == 100.0

    def test_the_summary_text_mentions_every_stage(self, run):
        text = format_summary(run[0])
        for needle in ("requirement", "spec", "red round 0", "blue (enumerate)", "residual risk", "evidence"):
            assert needle in text


class TestBlueChoices:

    def test_no_blue_means_no_rules_and_no_evidence(self):
        s = run_pipeline(REQ, seed=2, n_per_family=15, blue="none")
        assert s["rules"] == [] and s["evidence"] is None
        assert s["in_time_after"] == pytest.approx(s["in_time_before"])

    def test_the_llm_arm_needs_an_llm(self):
        with pytest.raises(ValueError):
            run_pipeline(REQ, n_per_family=5, blue="llm")

    def test_an_unknown_choice_is_rejected(self):
        with pytest.raises(ValueError):
            run_pipeline(REQ, n_per_family=5, blue="magic")

    def test_the_llm_arm_is_verified_like_the_others(self):
        jumpy = {"type": "jump", "id": "0x2A0", "field": "distance_m", "max_step": 0.3}
        llm = scripted(*([json.dumps({"rules": [jumpy, XCHK]})] * 3))
        s = run_pipeline(REQ, seed=1, n_per_family=30, blue="llm", blue_llm=llm)
        assert [r["type"] for r in s["rules"]] == ["cross_check"]      # the unsafe jump rule was rejected

    def test_random_proposals_also_work(self):
        s = run_pipeline(REQ, seed=1, n_per_family=30, blue="random")
        assert s["blue_cost"] == {"proposals": 9}


class TestCommandLine:

    def test_main_runs_end_to_end_and_writes_files(self, tmp_path, capsys):
        code = main(["--requirement", REQ, "--n", "12", "--blue", "enumerate", "--out", str(tmp_path / "o")])
        printed = capsys.readouterr().out
        assert code == 0 and "spec" in printed and "files written to" in printed
        assert (tmp_path / "o" / "pipeline_summary.json").exists()

    def test_main_reports_a_missing_deadline(self, capsys):
        assert main(["--requirement", "Brake promptly.", "--n", "5"]) == 1
        assert "pipeline stopped" in capsys.readouterr().out
