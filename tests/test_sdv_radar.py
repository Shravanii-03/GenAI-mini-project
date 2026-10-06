"""
tests/test_sdv_radar.py — optional redundant radar channel and the dual-sensor attacker.
"""
import dataclasses
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.attacks.library import ALL_ATTACKS, ATTACKS, make_attack
from sdv.runner import execute, run_once
from sdv.schemas import Scenario
from sdv.system.brake_chain import RADAR_ID, SENSOR_ID, ChainParams

SCEN = Scenario(v0_kmh=60, d0_m=30, cpu_load=0.4)
RADAR_ON = dataclasses.replace(ChainParams.from_config(), radar=True)


def frames_with_distance(chain, can_id):
    return [f for f in chain.bus.log if f.can_id == can_id and f.data.get("distance_m") is not None]


class TestRadarChannel:

    def test_off_by_default_so_earlier_experiments_are_unchanged(self):
        _, chain = execute(SCEN, 1)
        assert not any(f.can_id == RADAR_ID for f in chain.bus.log)

    def test_enabling_it_does_not_change_the_braking_outcome_for_a_seed(self):
        a = run_once(SCEN, 4)
        b = run_once(SCEN, 4, params=RADAR_ON)
        assert a.e2e_latency_ms == pytest.approx(b.e2e_latency_ms, abs=1.0)   # only extra bus load

    def test_radar_frames_are_periodic_and_carry_distance(self):
        _, chain = execute(SCEN, 2, params=RADAR_ON)
        radar = [f for f in chain.bus.log if f.can_id == RADAR_ID]
        assert len(radar) > 20
        gaps = {b.t_enqueued_us - a.t_enqueued_us for a, b in zip(radar, radar[1:])}
        assert gaps == {10_000}
        assert frames_with_distance(chain, RADAR_ID)

    def test_the_two_sensors_agree_when_there_is_no_attack(self):
        diffs = []
        for seed in range(15):
            _, chain = execute(SCEN, seed, params=RADAR_ON)
            s = {f.data["seq"]: f.data["distance_m"] for f in frames_with_distance(chain, SENSOR_ID)}
            r = {f.data["seq"]: f.data["distance_m"] for f in frames_with_distance(chain, RADAR_ID)}
            common = sorted(set(s) & set(r))
            diffs += [abs(s[k] - r[k]) for k in common[:30]]
        assert statistics.mean(diffs) < 0.3 and max(diffs) < 1.5

    def test_measurement_noise_is_independent_between_the_sensors(self):
        _, chain = execute(SCEN, 3, params=RADAR_ON)
        s = [f.data["distance_m"] for f in frames_with_distance(chain, SENSOR_ID)][:30]
        r = [f.data["distance_m"] for f in frames_with_distance(chain, RADAR_ID)][:30]
        assert s != r

    def test_perception_still_uses_only_the_primary_sensor(self):
        """Spoofing the radar alone must not change when the vehicle brakes."""
        from sdv.system.brake_chain import BrakeChain

        def onset(spoof_radar):
            chain = BrakeChain(SCEN, 5, RADAR_ON)
            if spoof_radar:
                def flt(frame, now):
                    if frame.can_id == RADAR_ID and frame.data.get("distance_m") is not None:
                        frame.data["distance_m"] += 60.0
                    return frame, 0
                chain.bus.add_tx_filter(flt)
            chain.run()
            return chain.timeline["brake_onset"]

        assert onset(True) == onset(False)


class TestDualMasquerade:

    def attack(self, name, bias=25):
        return make_attack(name, bias_m=bias, duration_ms=800, start_offset_ms=-300)

    def test_single_masquerade_leaves_the_radar_untouched(self):
        _, chain = execute(SCEN, 6, params=RADAR_ON, attacks=[self.attack("masquerade")])
        sensor = [f for f in frames_with_distance(chain, SENSOR_ID) if f.attack]
        radar = [f for f in frames_with_distance(chain, RADAR_ID) if f.attack]
        assert sensor and not radar

    def test_dual_masquerade_biases_both_channels_by_the_same_amount(self):
        _, chain = execute(SCEN, 6, params=RADAR_ON, attacks=[self.attack("dual_masquerade")])
        s = {f.data["seq"]: f.data["distance_m"] for f in frames_with_distance(chain, SENSOR_ID) if f.attack}
        r = {f.data["seq"]: f.data["distance_m"] for f in frames_with_distance(chain, RADAR_ID) if f.attack}
        assert s and r
        common = sorted(set(s) & set(r))
        assert statistics.mean(abs(s[k] - r[k]) for k in common) < 0.5       # channels stay consistent

    def test_dual_masquerade_delays_braking_like_the_single_one(self):
        base = statistics.mean(run_once(SCEN, s, params=RADAR_ON).e2e_latency_ms for s in range(10))
        dual = statistics.mean(run_once(SCEN, s, params=RADAR_ON, attacks=[self.attack("dual_masquerade")]
                                        ).e2e_latency_ms for s in range(10))
        assert dual > base + 20

    def test_make_attack_knows_the_new_family_and_the_original_registry_is_unchanged(self):
        assert make_attack("dual_masquerade").capability
        assert "dual_masquerade" in ALL_ATTACKS and "dual_masquerade" not in ATTACKS
        assert len(ATTACKS) == 8
