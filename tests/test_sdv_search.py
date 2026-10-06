"""
tests/test_sdv_search.py — search methods, problem objective and statistics helpers.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.attacks.library import make_attack
from sdv.metrics.stats import bootstrap_ci, median, wilson_interval
from sdv.monitors.monitors import DeadlineMonitor, FrequencyIDS, FusedMonitor, PlausibilityMonitor, observe
from sdv.runner import execute
from sdv.schemas import Scenario
from sdv.search.methods import (
    METHODS, BanditQLearning, BayesOpt, EvolutionStrategy, GridSearch, RandomSearch, run_search,
)
from sdv.search.problem import CLIP_MS, AttackSearchProblem, random_tight_scenario


class Synthetic:
    """Smooth 3-d objective with a small success region around a hidden point."""
    dim = 3

    def __init__(self, centre=(0.7, 0.3, 0.6)):
        self.centre = np.array(centre)
        self.evaluations = 0

    def evaluate(self, u, seed):
        self.evaluations += 1
        f = 1000 * (np.linalg.norm(np.asarray(u) - self.centre) - 0.12)
        return {"f": float(f), "success": f < 0}


class TestMethods:

    @pytest.mark.parametrize("name", sorted(METHODS))
    def test_every_method_stays_in_the_unit_cube_and_respects_budget(self, name):
        problem = Synthetic()
        m = METHODS[name](3, np.random.default_rng(0), budget=40)
        out = run_search(problem, m, budget=40, stop_on_success=False)
        assert out["evaluations"] == 40 and problem.evaluations == 40
        assert all(0.0 <= x <= 1.0 for h in out["history"] for x in h["u"])

    def test_stop_on_success_stops_at_first_success(self):
        out = run_search(Synthetic(centre=(0.5, 0.5, 0.5)), RandomSearch(3, np.random.default_rng(1)),
                         budget=500)
        assert out["first_success"] == out["evaluations"] or out["first_success"] is None

    def test_grid_search_covers_distinct_cells_before_repeating(self):
        g = GridSearch(2, np.random.default_rng(0), budget=16)
        pts = {tuple(np.round(g.ask(), 3)) for _ in range(16)}
        assert len(pts) == 16

    def test_same_seed_reproduces_the_same_search(self):
        runs = [run_search(Synthetic(), BayesOpt(3, np.random.default_rng(5)), 25, stop_on_success=False)
                for _ in range(2)]
        assert [h["f"] for h in runs[0]["history"]] == [h["f"] for h in runs[1]["history"]]

    def test_bayes_opt_beats_random_on_a_smooth_objective(self):
        def best(method_cls, seed):
            return run_search(Synthetic(), method_cls(3, np.random.default_rng(seed), budget=40), 40,
                              stop_on_success=False)["best_f"]
        bo = np.mean([best(BayesOpt, s) for s in range(8)])
        rs = np.mean([best(RandomSearch, s) for s in range(8)])
        assert bo < rs

    def test_es_improves_over_its_starting_point(self):
        out = run_search(Synthetic(), EvolutionStrategy(3, np.random.default_rng(2)), 60,
                         stop_on_success=False)
        assert out["best_f"] < out["history"][0]["f"]

    def test_q_learning_prefers_rewarded_cells(self):
        q = BanditQLearning(1, np.random.default_rng(0), cells=4, eps0=0.0, eps_min=0.0)
        for _ in range(20):
            u = q.ask()
            q.tell(u, -500.0 if u[0] > 0.75 else 500.0)
        assert int(np.argmax(q.q)) == 3

    def test_bayes_opt_accepts_a_warm_start(self):
        warm = [[0.7, 0.3, 0.6]] + [[0.1, 0.1, 0.1]] * 3
        bo = BayesOpt(3, np.random.default_rng(0), init_points=warm)
        assert np.allclose(bo.ask(), warm[0])


class TestProblem:

    def test_decode_maps_the_unit_cube_to_declared_bounds(self):
        p = AttackSearchProblem("gateway_delay", Scenario(), "hazard")
        lo = p.decode(np.zeros(p.dim))
        hi = p.decode(np.ones(p.dim))
        for key, (a, b) in p.bounds.items():
            assert lo[key] == pytest.approx(a) and hi[key] == pytest.approx(b)

    def test_integer_parameters_are_rounded(self):
        p = AttackSearchProblem("selective_suppression", Scenario(), "hazard")
        assert isinstance(p.decode(np.full(p.dim, 0.4))["k"], int)

    def test_hazard_objective_is_negative_exactly_when_there_is_a_collision(self):
        scenario = random_tight_scenario(random.Random(3))
        p = AttackSearchProblem("gateway_delay", scenario, "hazard")
        rng = np.random.default_rng(0)
        for i in range(25):
            u = rng.random(p.dim)
            out = p.evaluate(u, i)
            result, _ = execute(scenario, i, attacks=[make_attack("gateway_delay", **p.decode(u))])
            assert out["success"] == result.outcome.collision

    def test_stealth_objective_is_at_least_the_hazard_objective(self):
        scenario = random_tight_scenario(random.Random(4))
        train = [observe(execute(random_tight_scenario(random.Random(i)), 900 + i)[1]) for i in range(20)]
        mon = FusedMonitor([DeadlineMonitor(), FrequencyIDS(), PlausibilityMonitor()])
        mon.train(train)
        hazard = AttackSearchProblem("dos_flood", scenario, "hazard")
        stealth = AttackSearchProblem("dos_flood", scenario, "stealth", monitor=mon)
        rng = np.random.default_rng(1)
        for i in range(10):
            u = rng.random(hazard.dim)
            assert stealth.evaluate(u, i)["f"] >= hazard.evaluate(u, i)["f"]

    def test_objective_is_clipped(self):
        p = AttackSearchProblem("selective_suppression", Scenario(v0_kmh=60, d0_m=22), "hazard")
        out = p.evaluate(np.array([0.0, 1.0, 0.0]), 1)
        assert -CLIP_MS <= out["f"] <= CLIP_MS

    def test_stealth_mode_requires_a_monitor(self):
        with pytest.raises(ValueError):
            AttackSearchProblem("dos_flood", Scenario(), "stealth")


class TestStats:

    def test_wilson_interval_contains_the_estimate_and_is_bounded(self):
        lo, hi = wilson_interval(7, 20)
        assert 0 <= lo < 0.35 < hi <= 1
        assert wilson_interval(0, 10)[0] == 0.0 and wilson_interval(10, 10)[1] == 1.0

    def test_wilson_narrows_with_more_data(self):
        a, b = wilson_interval(5, 10), wilson_interval(50, 100)
        assert (b[1] - b[0]) < (a[1] - a[0])

    def test_bootstrap_ci_brackets_the_median(self):
        vals = [random.Random(0).gauss(10, 2) for _ in range(5)] + [9, 10, 11, 10.5, 9.5, 10.2, 9.8]
        lo, hi = bootstrap_ci(vals)
        assert lo <= median(vals) <= hi

    def test_empty_inputs_give_nan(self):
        assert math.isnan(wilson_interval(0, 0)[0]) and math.isnan(bootstrap_ci([])[0])
