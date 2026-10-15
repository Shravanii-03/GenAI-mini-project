"""
tests/test_sdv_assessment.py — defence assessment: which attacks does each defence leave open?
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.analysis.defence_assessment import ATTACK_VARIANTS, DEFENCES, assess, format_assessment, recommend

SUBSET = [v for v in ATTACK_VARIANTS if v[0] in ("masquerade", "dos_flood", "dos_flood (safety-bus node)",
                                                  "dual_masquerade (holds key)")]


@pytest.fixture(scope="module")
def result():
    return assess(n_per_variant=10, seed=4, variants=SUBSET)


def test_variants_cover_the_families_and_the_residual_cases():
    labels = [v[0] for v in ATTACK_VARIANTS]
    assert "masquerade" in labels and "dos_flood (safety-bus node)" in labels and "dual_masquerade (holds key)" in labels
    assert [d[0] for d in DEFENCES] == ["none", "radar_or", "+guard", "+auth", "+guard+auth"]


def test_failover_removes_the_forged_sensor_hazard(result):
    row = next(r for r in result["rows"] if r["variant"] == "masquerade")
    assert row["hazard"]["none"] > 0 and row["hazard"]["radar_or"] == 0


def test_the_guard_removes_the_untrusted_flood_but_not_the_safety_bus_flood(result):
    flood = next(r for r in result["rows"] if r["variant"] == "dos_flood")
    node = next(r for r in result["rows"] if r["variant"] == "dos_flood (safety-bus node)")
    assert flood["hazard"]["none"] > 0 and flood["hazard"]["+guard"] == 0
    assert node["hazard"]["+guard+auth"] > 0


def test_recommendation_is_the_cheapest_sufficient_defence(result):
    rec = {r["variant"]: r for r in result["recommendation"]}
    assert rec["masquerade"]["config"] == "radar_or"
    assert rec["dos_flood"]["config"] in ("+guard", "+guard+auth")
    assert rec["dos_flood (safety-bus node)"]["config"] is None
    assert "dos_flood (safety-bus node)" in result["open"] and "dual_masquerade (holds key)" in result["open"]


def test_the_bound_stays_sound(result):
    assert result["bound_violations"] == 0 and result["bound_runs"] > 100


def test_proven_safe_share_never_exceeds_the_non_hazard_share(result):
    for row in result["rows"]:
        for name in result["defences"]:
            assert row["proven_safe"][name] <= 1.0 - row["hazard"][name] + 1e-9


def test_recommend_logic_on_synthetic_rows():
    rows = [{"variant": "a", "hazard": {"none": 0.5, "x": 0.1, "y": 0.0}},
            {"variant": "b", "hazard": {"none": 0.4, "x": 0.4, "y": 0.4}},
            {"variant": "c", "hazard": {"none": 0.0, "x": 0.0, "y": 0.0}}]
    out = {r["variant"]: r for r in recommend(rows, ["none", "x", "y"], eps=0.02)}
    assert out["a"]["config"] == "y" and out["b"]["config"] is None and out["b"]["best_effort"] == "none"
    assert out["c"]["config"] == "none"


def test_small_samples_are_flagged_with_their_upper_bound(result):
    rec = {r["variant"]: r for r in result["recommendation"]}
    assert rec["masquerade"]["upper95_at_choice"] is not None and rec["masquerade"]["upper95_at_choice"] > 0.1


def test_text_report(result):
    text = format_assessment(result)
    assert "defence assessment" in text and "OPEN (no defence helps" in text and "open after every defence" in text
    assert "95% upper bound" in text
