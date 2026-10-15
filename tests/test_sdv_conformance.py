"""
tests/test_sdv_conformance.py — can a timing requirement be met, and proven?
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.analysis.conformance import check_requirement, default_configs, format_conformance


@pytest.fixture(scope="module")
def result():
    return check_requirement(100.0, n_scenarios=5, runs_per_scenario=2, seed=3)


def test_covers_both_configurations(result):
    assert set(result["configs"]) == {"baseline", "all defences"} and result["runs"] == 10


def test_the_bound_dominates_the_simulation(result):
    for cfg in result["configs"].values():
        assert cfg["bound_max_ms"] >= cfg["observed_max_ms"]
        assert cfg["bound_max_ms"] >= cfg["bound_median_ms"]


def test_a_generous_deadline_is_proven():
    r = check_requirement(1000.0, n_scenarios=4, runs_per_scenario=1, seed=1)
    assert all(c["verdict"] == "proven" for c in r["configs"].values())


def test_an_impossible_deadline_is_violated_in_simulation():
    r = check_requirement(10.0, n_scenarios=4, runs_per_scenario=1, seed=1)
    assert all(c["verdict"] == "violated in simulation" for c in r["configs"].values())


def test_the_smallest_provable_deadline_is_exactly_the_boundary(result):
    cfg = result["configs"]["baseline"]
    at = check_requirement(cfg["bound_max_ms"] + 0.01, n_scenarios=5, runs_per_scenario=1, seed=3)
    below = check_requirement(cfg["bound_max_ms"] - 0.5, n_scenarios=5, runs_per_scenario=1, seed=3)
    assert cfg["smallest_provable_deadline_ms"] == cfg["bound_max_ms"]
    assert at["configs"]["baseline"]["verdict"] == "proven"
    assert below["configs"]["baseline"]["verdict"] != "proven"


def test_breakdown_names_the_stages(result):
    breakdown = result["configs"]["baseline"]["worst_case_breakdown_ms"]
    assert {"perception", "decision", "actuator"} <= set(breakdown)


def test_the_defended_configuration_includes_authentication():
    cfgs = default_configs()
    assert cfgs["all defences"].auth and not cfgs["baseline"].auth


def test_text_report(result):
    text = format_conformance(result)
    assert "requirement conformance" in text and "smallest deadline that can be proven" in text
