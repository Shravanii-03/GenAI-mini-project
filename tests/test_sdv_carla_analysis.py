"""
tests/test_sdv_carla_analysis.py — pure helpers of the CARLA plant check (no CARLA needed).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.carla_check.analysis import bisect_ponr, closed_form_ponr_ms, fit_braking, model_speed, summarise
from sdv.plant.longitudinal import decel_for_road, ramp_seconds, simulate_braking
from sdv.schemas import Scenario


class TestFit:

    def test_recovers_the_parameters_of_a_noiseless_trace(self):
        t = np.arange(0, 3.0, 0.01)
        v = model_speed(t, 16.7, 7.0, 0.12)
        fit = fit_braking(t, v)
        assert fit["decel"] == pytest.approx(7.0, rel=0.03) and fit["ramp_s"] == pytest.approx(0.12, abs=0.01)

    def test_tolerates_sensor_noise(self):
        rng = np.random.default_rng(0)
        t = np.arange(0, 3.0, 0.01)
        v = model_speed(t, 20.0, 8.0, 0.05) + rng.normal(0, 0.03, len(t))
        fit = fit_braking(t, v)
        assert fit["decel"] == pytest.approx(8.0, rel=0.05) and fit["rmse"] < 0.1

    def test_model_speed_matches_the_emulator_plant_stopping_distance(self):
        v0, a, r = 16.7, decel_for_road("dry"), ramp_seconds()
        t = np.arange(0, 5.0, 0.0005)
        dist = float(np.sum(model_speed(t, v0, a, r)) * 0.0005)
        from sdv.carla_check.analysis import stopping_distance
        assert dist == pytest.approx(stopping_distance(v0, a, r), rel=0.01)


class TestPonr:

    def test_bisection_finds_the_emulator_plants_own_point_of_no_return(self):
        scenario = Scenario(v0_kmh=60, d0_m=24, cpu_load=0.3)
        collides = lambda ms: simulate_braking(scenario, ms / 1000.0).collision
        found = bisect_ponr(collides, 0.0, 1000.0, tol_ms=0.5)
        truth = closed_form_ponr_ms(60 / 3.6, 24, decel_for_road("dry"), ramp_seconds())
        assert found == pytest.approx(truth, abs=1.0)

    def test_edges(self):
        assert bisect_ponr(lambda ms: True, 0, 100) is None
        assert bisect_ponr(lambda ms: False, 0, 100) == 100

    def test_summary_reports_bias_and_error(self):
        rows = [{"carla_ms": 100.0, "assumed_ms": 110.0, "fitted_ms": 101.0},
                {"carla_ms": 200.0, "assumed_ms": 190.0, "fitted_ms": 199.0}]
        out = summarise(rows)
        assert out["assumed_ms"]["mean_abs_error_ms"] == pytest.approx(10.0)
        assert out["fitted_ms"]["mean_abs_error_ms"] == pytest.approx(1.0) and out["fitted_ms"]["n"] == 2
