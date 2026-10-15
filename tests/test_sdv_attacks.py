"""
tests/test_sdv_attacks.py — attacks act on the bus and have measurable, physical effects.
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.attacks.library import ATTACKS, make_attack
from sdv.runner import execute, run_once
from sdv.schemas import Scenario
from sdv.system.brake_chain import SENSOR_ID

SCEN = Scenario(v0_kmh=60, d0_m=30, cpu_load=0.5)
SEEDS = range(25)


def mean_latency(attack_factory=None, seeds=SEEDS, scenario=SCEN):
    lats = []
    for s in seeds:
        attacks = [attack_factory()] if attack_factory else []
        r = run_once(scenario, seed=s, attacks=attacks)
        lats.append(r.e2e_latency_ms if r.braked else float("inf"))
    return statistics.mean(lats)


BASE = mean_latency()


class TestRegistry:

    def test_every_family_builds_with_defaults_and_declares_bounds(self):
        for name, cls in ATTACKS.items():
            attack = make_attack(name)
            assert attack.capability
            assert "duration_ms" in cls.PARAM_BOUNDS
            assert attack.name == name

    def test_unknown_attack_is_rejected(self):
        try:
            make_attack("does_not_exist")
            assert False
        except KeyError:
            pass


class TestInjectionAttacks:

    def test_dos_flood_delays_braking_and_marks_attack_frames(self):
        r, chain = execute(SCEN, 1, attacks=[make_attack("dos_flood", rate_hz=4000, duration_ms=300,
                                                         start_offset_ms=-20)])
        assert r.e2e_latency_ms > BASE + 100
        flood = [f for f in chain.bus.log if f.attack]
        assert flood and all(f.can_id == 0x010 for f in flood)
        assert r.attack_windows_ms[0]["name"] == "dos_flood"

    def test_flood_stops_after_its_window(self):
        r, chain = execute(SCEN, 2, attacks=[make_attack("dos_flood", rate_hz=2000, duration_ms=100,
                                                         start_offset_ms=0)])
        end_us = chain.attack_windows[0][2]
        assert max(f.t_enqueued_us for f in chain.bus.log if f.attack) < end_us

    def test_low_and_slow_uses_less_bus_than_a_full_flood(self):
        _, flood = execute(SCEN, 3, attacks=[make_attack("dos_flood", rate_hz=3000, duration_ms=300)])
        _, slow = execute(SCEN, 3, attacks=[make_attack("low_slow_dos", duty=0.2, duration_ms=300)])
        assert sum(f.attack for f in slow.bus.log) < sum(f.attack for f in flood.bus.log) / 2

    def test_priority_abuse_uses_a_legitimate_id_and_delays_sensor_frames(self):
        r, chain = execute(SCEN, 4, attacks=[make_attack("priority_abuse", rate_hz=3000,
                                                         duration_ms=300, start_offset_ms=-20)])
        assert {f.can_id for f in chain.bus.log if f.attack} == {0x1A3}
        assert r.stage_ms["sensor_bus"] > 1.0


class TestGatewayAttacks:

    def test_gateway_delay_adds_about_the_configured_delay(self):
        lat = mean_latency(lambda: make_attack("gateway_delay", delay_ms=60, duration_ms=500,
                                               start_offset_ms=-50))
        assert 40 < lat - BASE < 90

    def test_jitter_injection_adds_less_delay_than_fixed_hold_of_same_size(self):
        jitter = mean_latency(lambda: make_attack("jitter_injection", delay_ms=60, duration_ms=500,
                                                  start_offset_ms=-50))
        fixed = mean_latency(lambda: make_attack("gateway_delay", delay_ms=60, duration_ms=500,
                                                 start_offset_ms=-50))
        assert BASE < jitter < fixed

    def test_suppressing_every_sensor_frame_means_the_vehicle_never_brakes(self):
        r = run_once(SCEN, 5, attacks=[make_attack("selective_suppression", k=1, duration_ms=5000,
                                                   start_offset_ms=-50)])
        assert not r.braked and r.outcome.collision and r.margin_ms is None

    def test_suppressing_every_second_frame_costs_about_one_period(self):
        lat = mean_latency(lambda: make_attack("selective_suppression", k=2, duration_ms=500,
                                               start_offset_ms=-50))
        assert 0 < lat - BASE < 25

    def test_dropped_frames_are_recorded_for_ground_truth(self):
        _, chain = execute(SCEN, 6, attacks=[make_attack("selective_suppression", k=1, duration_ms=300,
                                                         start_offset_ms=-50)])
        assert chain.bus.dropped and all(f.attack for f in chain.bus.dropped)


class TestSpoofingAttacks:

    def test_drift_spoof_delays_braking_without_touching_frame_timing(self):
        r, chain = execute(SCEN, 7, attacks=[make_attack("sensor_drift_spoof", rate_m_per_s=25,
                                                         duration_ms=800, start_offset_ms=-400)])
        assert r.e2e_latency_ms > BASE + 100
        sensors = [f for f in chain.bus.log if f.can_id == SENSOR_ID]
        gaps = [b.t_enqueued_us - a.t_enqueued_us for a, b in zip(sensors, sensors[1:])]
        assert set(gaps) == {10_000}

    def test_masquerade_bias_delays_braking_and_zero_bias_does_not(self):
        biased = mean_latency(lambda: make_attack("masquerade", bias_m=25, phase_shift_ms=0,
                                                  duration_ms=800, start_offset_ms=-50))
        harmless = mean_latency(lambda: make_attack("masquerade", bias_m=0, phase_shift_ms=0,
                                                    duration_ms=800, start_offset_ms=-50))
        assert biased > BASE + 20
        assert abs(harmless - BASE) < 3

    def test_spoofed_distance_is_larger_than_true_distance(self):
        _, chain = execute(SCEN, 8, attacks=[make_attack("masquerade", bias_m=20, duration_ms=800,
                                                         start_offset_ms=-50)])
        spoofed = [f for f in chain.bus.log if f.can_id == SENSOR_ID and f.attack]
        assert spoofed and all(f.data["distance_m"] >= 20 for f in spoofed)


class TestHazardLink:

    def test_attack_can_turn_a_safe_run_into_a_collision(self):
        tight = Scenario(v0_kmh=60, d0_m=20, cpu_load=0.3)
        benign = [run_once(tight, seed=s) for s in range(20)]
        attacked = [run_once(tight, seed=s, attacks=[make_attack("gateway_delay", delay_ms=80,
                                                                 duration_ms=500, start_offset_ms=-50)])
                    for s in range(20)]
        assert sum(r.outcome.collision for r in benign) == 0
        assert sum(r.outcome.collision for r in attacked) == 20
