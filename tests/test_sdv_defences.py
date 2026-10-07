"""
tests/test_sdv_defences.py — gateway guard, message authentication, fail-safe watchdog.
"""
import dataclasses
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.analysis.bounds import FLOOD_FAMILIES, FORGING, latency_bound_ms, proven_safe
from sdv.attacks.library import ALL_ATTACKS, PhantomObstacle, make_attack
from sdv.bus.guard import ALLOWED_FROM_UNTRUSTED, SAFETY_BUS_SRC, UNTRUSTED_SRC, GatewayGuard
from sdv.monitors.monitors import observe
from sdv.runner import execute
from sdv.schemas import CanFrame, Scenario
from sdv.search.problem import AttackSearchProblem, random_tight_scenario
from sdv.system.brake_chain import RADAR_ID, ChainParams

HARD = random_tight_scenario(random.Random(0))
FAR = Scenario(v0_kmh=60, d0_m=250, cpu_load=0.3)


def chain(**kw):
    kw.setdefault("mitigation", "radar_or")
    return dataclasses.replace(ChainParams.from_config(), radar=True, **kw)


def run(scenario, attack, seed=3, **kw):
    return execute(scenario, seed, chain(**kw), attacks=[attack])


FLOOD = dict(rate_hz=6000.0, duration_ms=250.0, start_offset_ms=0.0)
FORGE = dict(bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0.0, duration_ms=800.0)


class TestGatewayGuard:

    def frame(self, can_id, src=UNTRUSTED_SRC):
        return CanFrame(can_id=can_id, src=src)

    def test_frames_from_other_senders_pass_untouched(self):
        guard = GatewayGuard()
        assert guard(self.frame(0x010, "sensor"), 0)[0] is not None
        assert guard(self.frame(0x010, SAFETY_BUS_SRC), 0)[0] is not None

    def test_untrusted_frames_with_unlisted_ids_are_dropped(self):
        guard = GatewayGuard()
        assert guard(self.frame(0x010), 0)[0] is None and guard.blocked == 1

    def test_whitelisted_ids_are_rate_limited(self):
        guard = GatewayGuard()
        can_id = next(iter(ALLOWED_FROM_UNTRUSTED))
        passed = sum(guard(self.frame(can_id), t * 100)[0] is not None for t in range(2000))   # 10 kHz for 0.2 s
        assert passed <= 2 + 0.2 * 2 * 1000 / ALLOWED_FROM_UNTRUSTED[can_id] + 1

    def test_a_polite_sender_is_not_blocked(self):
        guard = GatewayGuard()
        can_id = next(iter(ALLOWED_FROM_UNTRUSTED))
        period_us = int(ALLOWED_FROM_UNTRUSTED[can_id] * 1000)
        assert all(guard(self.frame(can_id), k * period_us)[0] is not None for k in range(30))

    def test_the_guard_stops_a_flood_from_the_untrusted_segment(self):
        flood = lambda: make_attack("dos_flood", **FLOOD)
        assert run(HARD, flood())[0].outcome.collision
        assert not run(HARD, flood(), gateway_guard=True)[0].outcome.collision

    def test_the_guard_cannot_stop_a_node_on_the_safety_bus(self):
        flood = lambda: make_attack("dos_flood", segment="safety", **FLOOD)
        assert run(HARD, flood(), gateway_guard=True)[0].outcome.collision

    def test_the_guard_does_not_touch_benign_timing(self):
        a = execute(HARD, 9, chain())[0].e2e_latency_ms
        b = execute(HARD, 9, chain(gateway_guard=True))[0].e2e_latency_ms
        assert a == pytest.approx(b, abs=1e-9)


class TestAuthentication:

    def test_a_forged_frame_is_rejected_so_a_single_channel_forgery_is_harmless_even_without_failover(self):
        forge = lambda: make_attack("masquerade", **FORGE)
        assert run(HARD, forge(), mitigation="none")[0].outcome.collision
        result, ch = run(HARD, forge(), mitigation="none", auth=True)
        assert not result.outcome.collision and ch.rejected_frames > 0

    def test_dual_forgery_is_defeated_by_authentication_plus_the_watchdog(self):
        forge = lambda: make_attack("dual_masquerade", bias_m=40.0, start_offset_ms=0.0, duration_ms=800.0)
        assert run(HARD, forge())[0].outcome.collision
        result, ch = run(HARD, forge(), auth=True)
        assert not result.outcome.collision and ch.trigger_source == "watchdog"

    def test_an_attacker_that_holds_the_key_is_not_stopped(self):
        forge = make_attack("dual_masquerade", bias_m=40.0, holds_key=True, start_offset_ms=0.0, duration_ms=800.0)
        result, ch = run(HARD, forge, auth=True)
        assert result.outcome.collision and ch.rejected_frames == 0

    def test_delay_attacks_are_not_forgeries_and_pass_authentication(self):
        attack = make_attack("gateway_delay", delay_ms=60.0, duration_ms=300.0, start_offset_ms=0.0)
        _, ch = run(HARD, attack, auth=True)
        assert ch.rejected_frames == 0

    def test_verification_adds_a_small_benign_latency(self):
        a = execute(HARD, 11, chain())[0].e2e_latency_ms
        b = execute(HARD, 11, chain(auth=True))[0].e2e_latency_ms
        assert 0 < b - a < 5.0

    def test_authentication_closes_the_phantom_obstacle_hole(self):
        phantom = lambda: PhantomObstacle(channel_id=RADAR_ID, report_m=8.0, start_offset_ms=0, duration_ms=400)
        assert run(FAR, phantom())[0].braked
        assert not run(FAR, phantom(), auth=True)[0].braked

    def test_but_corrupting_both_channels_provokes_a_fail_safe_stop_when_nothing_is_there(self):
        corrupt = make_attack("dual_masquerade", bias_m=5.0, start_offset_ms=0, duration_ms=400)
        result, ch = run(FAR, corrupt, auth=True)
        assert result.braked and ch.trigger_source == "watchdog"

    def test_the_watchdog_is_quiet_without_an_attack(self):
        for seed in range(15):
            assert execute(random_tight_scenario(random.Random(seed)), seed, chain(auth=True))[1].trigger_source != "watchdog"

    def test_monitors_never_see_the_internal_forgery_flags(self):
        _, ch = run(HARD, make_attack("masquerade", **FORGE))
        frames, _ = observe(ch)
        assert not any("forged" in f.data or "holds_key" in f.data for f in frames)
        assert any(f.get("forged") for f in (x.data for x in ch.bus.log))


@pytest.mark.parametrize("config", [dict(gateway_guard=True), dict(auth=True), dict(gateway_guard=True, auth=True)])
@pytest.mark.parametrize("family", list(ALL_ATTACKS))
def test_bound_stays_sound_under_every_defence(family, config):
    problem = AttackSearchProblem(family, HARD)
    rng = np.random.default_rng(5)
    for i in range(6):
        params = problem.decode(rng.random(problem.dim))
        if family in FLOOD_FAMILIES:
            params["segment"] = "safety" if i % 2 else "untrusted"
        if family in FORGING:
            params["holds_key"] = bool(i % 3 == 0)
        res = execute(HARD, 200 + i, chain(**config), attacks=[make_attack(family, **params)])[0]
        if res.e2e_latency_ms is not None:
            bound = latency_bound_ms(HARD, make_attack(family, **params), chain(**config)).total_ms
            assert res.e2e_latency_ms <= bound + 1e-6


class TestBoundWithDefences:

    def test_guard_makes_an_untrusted_flood_provably_harmless(self):
        flood = make_attack("dos_flood", **FLOOD)
        assert not proven_safe(HARD, flood, chain())
        assert proven_safe(HARD, flood, chain(gateway_guard=True))

    def test_guard_does_not_help_the_bound_for_a_safety_bus_flood(self):
        flood = make_attack("dos_flood", segment="safety", **FLOOD)
        assert not proven_safe(HARD, flood, chain(gateway_guard=True))

    def test_auth_plus_watchdog_proves_a_dual_forgery_safe_but_not_a_key_holder(self):
        dual = lambda **kw: make_attack("dual_masquerade", bias_m=40.0, start_offset_ms=0, duration_ms=800, **kw)
        assert not proven_safe(HARD, dual(), chain())
        assert proven_safe(HARD, dual(), chain(auth=True))
        assert not proven_safe(HARD, dual(holds_key=True), chain(auth=True))
