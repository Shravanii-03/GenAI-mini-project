"""
tests/test_sdv_mitigation.py — radar failover policies in the emulated braking chain.
"""
import dataclasses
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.attacks.library import PhantomObstacle, make_attack
from sdv.runner import execute
from sdv.schemas import Scenario
from sdv.search.problem import random_tight_scenario
from sdv.system.brake_chain import MITIGATIONS, RADAR_ID, SENSOR_ID, BrakeChain, ChainParams

TIGHT = Scenario(v0_kmh=60, d0_m=30, cpu_load=0.3)
HARD = random_tight_scenario(random.Random(0))     # a benign run is safe, a delayed brake is not
FAR = Scenario(v0_kmh=60, d0_m=250, cpu_load=0.3)


def params(policy):
    return dataclasses.replace(ChainParams.from_config(), radar=True, mitigation=policy)


def test_policies_are_declared_and_unknown_ones_rejected():
    assert MITIGATIONS == ("none", "radar_or", "disagree_brake")
    with pytest.raises(ValueError):
        BrakeChain(TIGHT, 0, dataclasses.replace(ChainParams.from_config(), mitigation="magic"))


def test_a_mitigation_switches_the_radar_on():
    _, chain = execute(TIGHT, 1, dataclasses.replace(ChainParams.from_config(), mitigation="radar_or"))
    assert any(f.can_id == RADAR_ID for f in chain.bus.log)


def test_default_policy_is_none_and_primary_sensor_triggers():
    _, chain = execute(TIGHT, 2, params("none"))
    assert chain.trigger_source == "sensor"


def test_benign_braking_time_is_barely_changed_by_voting():
    base = execute(TIGHT, 3, params("none"))[0].e2e_latency_ms
    voted = execute(TIGHT, 3, params("radar_or"))[0].e2e_latency_ms
    assert abs(voted - base) < 12.0          # at most a sampling period of difference plus bus jitter


def test_failover_defeats_a_constant_bias_masquerade_on_the_primary_sensor():
    attack = lambda: make_attack("masquerade", bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0, duration_ms=800)
    plain = execute(HARD, 5, params("none"), attacks=[attack()])[0]
    protected, chain = execute(HARD, 5, params("radar_or"), attacks=[attack()])
    assert plain.outcome.collision and not protected.outcome.collision
    assert chain.trigger_source == "radar"


def test_dual_masquerade_still_defeats_the_failover():
    attack = make_attack("dual_masquerade", bias_m=40.0, start_offset_ms=0, duration_ms=800)
    result = execute(HARD, 5, params("radar_or"), attacks=[attack])[0]
    assert result.outcome.collision


def test_voting_opens_an_availability_hole_on_the_radar_channel():
    attack = lambda: PhantomObstacle(channel_id=RADAR_ID, report_m=8.0, start_offset_ms=0, duration_ms=400)
    assert not execute(FAR, 6, params("none"), attacks=[attack()])[0].braked
    assert execute(FAR, 6, params("radar_or"), attacks=[attack()])[0].braked


def test_a_forged_primary_sensor_provokes_braking_under_every_policy():
    attack = lambda: PhantomObstacle(channel_id=SENSOR_ID, report_m=8.0, start_offset_ms=0, duration_ms=400)
    for policy in MITIGATIONS:
        assert execute(FAR, 7, params(policy), attacks=[attack()])[0].braked


def test_disagreement_policy_can_trigger_on_the_disagreement_itself():
    # sensor says far (bias), radar says near but not yet below the TTC trigger -> precautionary stop
    scenario = Scenario(v0_kmh=60, d0_m=45, cpu_load=0.3)
    attack = make_attack("masquerade", bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0, duration_ms=800)
    _, chain = execute(scenario, 8, params("disagree_brake"), attacks=[attack])
    assert chain.trigger_source in ("disagreement", "radar")
