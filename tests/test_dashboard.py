"""
tests/test_dashboard.py — the browser dashboard (dashboard/rebuilt_app.py) renders every tab without errors.

Uses Streamlit's own headless test harness; no browser or server is needed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from sdv.pipeline import run_pipeline  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "rebuilt_app.py")
REQ = "Brake within 100 ms if an obstacle is detected."


def fresh():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def metric_values(at):
    return {m.label: m.value for m in at.metric}


@pytest.fixture(scope="module")
def summary_and_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("dash")
    return run_pipeline(REQ, seed=1, n_per_family=30, blue="enumerate", out_dir=str(out), assess_n=8), out


def test_first_load_has_no_errors_and_shows_the_explorer():
    at = fresh()
    assert not at.exception
    values = metric_values(at)
    assert {"Point of no return", "Brake latency", "Outcome", "Chain started by"} <= set(values)
    assert values["Outcome"] == "safe stop"


def test_attack_explorer_shows_a_collision_for_a_forged_sensor_and_the_failover_prevents_it():
    at = fresh()
    attack = next(s for s in at.selectbox if s.label == "Attack")
    attack.select("masquerade").run()
    for slider in at.slider:                                    # strongest forgery, starting with the obstacle
        if slider.label == "bias_m":
            slider.set_value(40.0)
        if slider.label == "duration_ms":
            slider.set_value(800.0)
        if slider.label == "start_offset_ms":
            slider.set_value(0.0)
    at.run()
    assert not at.exception
    assert metric_values(at)["Outcome"] == "COLLISION"
    next(s for s in at.selectbox if s.label == "Defence configuration").select("radar_or").run()
    assert not at.exception and metric_values(at)["Outcome"] == "safe stop"


def test_every_attack_family_renders_in_the_explorer():
    at = fresh()
    families = next(s for s in at.selectbox if s.label == "Attack").options
    for family in families:
        next(s for s in at.selectbox if s.label == "Attack").select(family).run()
        assert not at.exception, family


def test_loaded_run_fills_the_pipeline_conformance_and_defence_tabs(summary_and_dir):
    summary, out = summary_and_dir
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["summary"] = summary
    at.session_state["run_dir"] = out
    at.run()
    assert not at.exception
    assert metric_values(at)["Attack-induced hazards (round 0)"] == str(summary["hazards_round0"])
    frames = [df.value for df in at.dataframe]
    assert any("analytic worst case (ms)" in f.columns for f in frames)          # conformance table
    assert any("cheapest sufficient defence" in f.columns for f in frames)       # defence table
    if summary["rules"]:
        assert any(c.value for c in at.code)                                     # the verified rule


def test_the_audit_button_reruns_every_check(summary_and_dir):
    summary, out = summary_and_dir
    if not summary["evidence"]:
        pytest.skip("no evidence bundle in this run")
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["summary"] = summary
    at.session_state["run_dir"] = out
    at.run()
    next(b for b in at.button if "Re-run every check" in b.label).click().run()
    assert not at.exception
    assert any(s.value.endswith("checks re-verified") for s in at.success)


def test_results_tab_lists_the_experiments():
    at = fresh()
    experiment = next(s for s in at.selectbox if s.label == "Experiment")
    assert any("E12" in o for o in experiment.options) and any("E13" in o for o in experiment.options)
