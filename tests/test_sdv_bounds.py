"""
tests/test_sdv_bounds.py — analytic worst-case latency bound: soundness against the emulator.
"""
import dataclasses
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.analysis.bounds import latency_bound_ms, max_safe_value, proven_safe, response_time_us
from sdv.attacks.library import ALL_ATTACKS, PhantomObstacle, make_attack
from sdv.plant.longitudinal import latest_safe_latency_ms
from sdv.runner import execute
from sdv.schemas import Scenario
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import RADAR_ID, SENSOR_ID, ChainParams

HARD = random_tight_scenario(random.Random(0))


def chain(policy="none"):
    return dataclasses.replace(ChainParams.from_config(), radar=True, mitigation=policy)


def observed(scenario, attack, seed, policy="none"):
    result, _ = execute(scenario, seed, chain(policy), attacks=[attack] if attack else [])
    return result


class TestResponseTime:

    def test_highest_priority_frame_waits_only_for_blocking(self):
        r = response_time_us(0x001)
        assert 270 <= r <= 2 * 270 + 1                  # at most one blocking frame plus its own time

    def test_lower_priority_frames_respond_no_faster(self):
        assert response_time_us(RADAR_ID) >= response_time_us(SENSOR_ID) >= response_time_us(0x100)


class TestBenign:

    def test_bound_dominates_every_observed_latency(self):
        bound = latency_bound_ms(HARD, None, chain()).total_ms
        assert all(observed(HARD, None, s).e2e_latency_ms <= bound for s in range(40))

    def test_bound_is_not_absurdly_loose(self):
        bound = latency_bound_ms(HARD, None, chain()).total_ms
        mean = sum(observed(HARD, None, s).e2e_latency_ms for s in range(20)) / 20
        assert bound < 3.0 * mean


@pytest.mark.parametrize("family", list(ALL_ATTACKS))
@pytest.mark.parametrize("policy", ["none", "radar_or"])
def test_bound_holds_for_every_family_on_random_attack_parameters(family, policy):
    import numpy as np  # noqa: PLC0415
    problem = AttackSearchProblem(family, HARD)
    nprng = np.random.default_rng(11)
    for i in range(12):
        attack = make_attack(family, **problem.decode(nprng.random(problem.dim)))
        res = observed(HARD, attack, 100 + i, policy)
        if res.e2e_latency_ms is not None:
            assert res.e2e_latency_ms <= latency_bound_ms(HARD, attack, chain(policy)).total_ms + 1e-6


def test_regression_overloaded_flood_started_before_the_obstacle():
    # offered load above bus capacity: the backlog outlives the flood; an early version of the bound missed it
    kw = dict(rate_hz=3424.69, duration_ms=237.98, start_offset_ms=-73.68)
    bound = latency_bound_ms(HARD, make_attack("dos_flood", **kw), chain()).total_ms
    for seed in range(12):
        assert observed(HARD, make_attack("dos_flood", **kw), seed).e2e_latency_ms <= bound


class TestVerdicts:

    def test_proven_safe_implies_no_collision_for_any_seed(self):
        attack = lambda: make_attack("gateway_delay", delay_ms=5, duration_ms=100, start_offset_ms=0)
        assert proven_safe(HARD, attack(), chain())
        assert not any(observed(HARD, attack(), s).outcome.collision for s in range(30))

    def test_a_hazardous_attack_is_not_proven_safe(self):
        attack = make_attack("masquerade", bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0, duration_ms=800)
        assert observed(HARD, attack, 3).outcome.collision
        assert not proven_safe(HARD, attack, chain())

    def test_radar_failover_proves_a_single_channel_forgery_safe(self):
        attack = make_attack("masquerade", bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0, duration_ms=800)
        assert proven_safe(HARD, attack, chain("radar_or"))

    def test_dual_masquerade_cannot_be_proven_safe_by_redundancy(self):
        attack = make_attack("dual_masquerade", bias_m=40.0, start_offset_ms=0, duration_ms=800)
        assert not proven_safe(HARD, attack, chain("radar_or"))

    def test_bound_grows_with_attack_strength(self):
        weak = latency_bound_ms(HARD, make_attack("gateway_delay", delay_ms=10, duration_ms=300, start_offset_ms=0))
        strong = latency_bound_ms(HARD, make_attack("gateway_delay", delay_ms=150, duration_ms=300, start_offset_ms=0))
        assert strong.total_ms > weak.total_ms
        short = latency_bound_ms(HARD, make_attack("dos_flood", rate_hz=6000, duration_ms=50, start_offset_ms=0))
        long_ = latency_bound_ms(HARD, make_attack("dos_flood", rate_hz=6000, duration_ms=300, start_offset_ms=0))
        assert long_.total_ms > short.total_ms

    def test_phantom_obstacle_is_out_of_scope(self):
        with pytest.raises(ValueError):
            latency_bound_ms(HARD, PhantomObstacle())


class TestEnvelope:

    def test_max_safe_duration_is_just_provable(self):
        scen = Scenario(v0_kmh=60, d0_m=24, cpu_load=0.3)
        fixed = {"rate_hz": 6000, "start_offset_ms": 0}
        d = max_safe_value(scen, "dos_flood", "duration_ms", fixed)
        assert d is not None
        ok = make_attack("dos_flood", duration_ms=d, **fixed)
        assert latency_bound_ms(scen, ok).total_ms <= latest_safe_latency_ms(scen)
        if d < ALL_ATTACKS["dos_flood"].PARAM_BOUNDS["duration_ms"][1]:
            over = make_attack("dos_flood", duration_ms=d + 5, **fixed)
            assert latency_bound_ms(scen, over).total_ms > latest_safe_latency_ms(scen)

    def test_returns_none_when_nothing_is_provable(self):
        scen = Scenario(v0_kmh=100, d0_m=20, cpu_load=0.5)        # point of no return already passed
        assert max_safe_value(scen, "dos_flood", "duration_ms", {"rate_hz": 6000, "start_offset_ms": 0}) is None


def test_regression_flood_that_ends_before_the_obstacle_but_leaves_a_backlog():
    # found by the adversarial search: 548 queued flood frames take longer to drain than the flood lasted
    scen = Scenario(v0_kmh=61.62304265009129, d0_m=21.154429773301395, cpu_load=0.48610044282444453)
    kw = dict(rate_hz=5962.5, duration_ms=91.94, start_offset_ms=-100.0)
    bound = latency_bound_ms(scen, make_attack("dos_flood", **kw), chain()).total_ms
    for seed in range(10):
        assert observed(scen, make_attack("dos_flood", **kw), seed).e2e_latency_ms <= bound
