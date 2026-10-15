"""
tests/test_sdv_mac.py — the real truncated HMAC authentication mode (auth_mode="hmac").
"""
import dataclasses
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.attacks.library import make_attack
from sdv.runner import execute
from sdv.schemas import CanFrame
from sdv.search.problem import random_tight_scenario
from sdv.security.mac import FrameMac, encode_payload
from sdv.system.brake_chain import SENSOR_ID, BrakeChain, ChainParams

HARD = random_tight_scenario(random.Random(0))
FORGE = dict(bias_m=40.0, phase_shift_ms=0.0, start_offset_ms=0.0, duration_ms=800.0)


def chain(mode="hmac", bits=24, mitigation="radar_or"):
    return dataclasses.replace(ChainParams.from_config(), radar=True, mitigation=mitigation, auth=True,
                               auth_mode=mode, mac_bits=bits)


class TestFrameMac:

    def test_tag_is_deterministic_and_within_its_length(self):
        mac = FrameMac(b"k" * 32, bits=24)
        payload = encode_payload(21.5, 16.7, True)
        assert mac.tag(0x2A0, 7, payload) == mac.tag(0x2A0, 7, payload)
        assert 0 <= mac.tag(0x2A0, 7, payload) < 2 ** 24

    def test_any_change_breaks_the_tag(self):
        mac = FrameMac(b"k" * 32, bits=32)
        payload = encode_payload(21.5, 16.7, True)
        tag = mac.tag(0x2A0, 7, payload)
        assert mac.verify(0x2A0, 7, payload, tag)
        assert not mac.verify(0x2A0, 7, encode_payload(61.5, 16.7, True), tag)      # altered distance
        assert not mac.verify(0x2A0, 8, payload, tag)                                # altered counter
        assert not mac.verify(0x2B0, 7, payload, tag)                                # another identifier
        assert not mac.verify(0x2A0, 7, payload, None)

    def test_a_different_key_gives_a_different_tag(self):
        payload = encode_payload(21.5, 16.7, True)
        assert FrameMac(b"a" * 32, 32).tag(1, 1, payload) != FrameMac(b"b" * 32, 32).tag(1, 1, payload)

    def test_bits_are_validated(self):
        with pytest.raises(ValueError):
            FrameMac(b"k", bits=0)

    def test_payload_quantisation_is_millimetres(self):
        assert encode_payload(21.5004, 16.7, True) == encode_payload(21.5001, 16.7, True)
        assert encode_payload(21.5, 16.7, True) != encode_payload(21.502, 16.7, True)


class TestInTheChain:

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            BrakeChain(HARD, 1, dataclasses.replace(chain(), auth_mode="rot13"))

    def test_benign_runs_reject_nothing_and_match_the_idealised_mode_exactly(self):
        for seed in range(15):
            scenario = random_tight_scenario(random.Random(seed))
            real, c1 = execute(scenario, seed, chain("hmac"))
            ideal, c2 = execute(scenario, seed, chain("ideal"))
            assert c1.rejected_frames == 0
            assert real.e2e_latency_ms == ideal.e2e_latency_ms and c1.trigger_source == c2.trigger_source

    def test_a_forged_sensor_is_rejected_by_the_real_mac(self):
        result, c = execute(HARD, 3, chain("hmac", mitigation="none"), attacks=[make_attack("masquerade", **FORGE)])
        assert c.rejected_frames > 0 and not result.outcome.collision

    def test_an_attacker_that_holds_the_key_is_not_stopped(self):
        attack = make_attack("dual_masquerade", bias_m=40.0, holds_key=True, start_offset_ms=0.0, duration_ms=800.0)
        result, c = execute(HARD, 3, chain("hmac"), attacks=[attack])
        assert result.outcome.collision and c.rejected_frames == 0

    def test_dual_forgery_is_still_defeated_by_the_watchdog(self):
        attack = make_attack("dual_masquerade", bias_m=40.0, start_offset_ms=0.0, duration_ms=800.0)
        result, c = execute(HARD, 3, chain("hmac"), attacks=[attack])
        assert not result.outcome.collision and c.trigger_source == "watchdog"

    def test_hmac_and_ideal_modes_decide_alike_for_a_24_bit_mac(self):
        same = 0
        for seed in range(12):
            attack = lambda: make_attack("dual_masquerade", bias_m=30.0, start_offset_ms=0.0, duration_ms=600.0)
            a, ca = execute(HARD, seed, chain("hmac"), attacks=[attack()])
            b, cb = execute(HARD, seed, chain("ideal"), attacks=[attack()])
            same += (a.outcome.collision == b.outcome.collision and ca.trigger_source == cb.trigger_source)
        assert same == 12

    def test_a_short_mac_lets_forged_frames_through_at_about_2_to_the_minus_bits(self):
        accepted = total = 0
        for seed in range(500):
            attack = make_attack("masquerade", **FORGE)
            _, c = execute(HARD, seed, chain("hmac", bits=8, mitigation="none"), attacks=[attack])
            forged = sum(1 for f in c.bus.log if f.can_id == SENSOR_ID and f.data.get("forged"))
            accepted += forged - c.rejected_frames
            total += forged
        rate = accepted / total
        assert total > 7000 and 1 / 256 / 3 < rate < 1 / 256 * 3          # about 0.4%

    def test_a_24_bit_mac_lets_nothing_through_in_the_same_experiment(self):
        accepted = 0
        for seed in range(80):
            _, c = execute(HARD, seed, chain("hmac", bits=24, mitigation="none"),
                           attacks=[make_attack("masquerade", **FORGE)])
            forged = sum(1 for f in c.bus.log if f.can_id == SENSOR_ID and f.data.get("forged"))
            accepted += forged - c.rejected_frames
        assert accepted == 0

    def test_replayed_or_reordered_frames_are_rejected_by_the_freshness_counter(self):
        c = BrakeChain(HARD, 1, chain("hmac"))
        genuine = []
        for seq in (1, 2, 3):
            f = CanFrame(can_id=SENSOR_ID, src="sensor", data={"seq": seq, "obstacle": False, "distance_m": None,
                                                                "speed_ms": 16.7})
            c.sign(f)
            genuine.append(f)
        assert c._frame_valid(genuine[0], "sensor") and c._frame_valid(genuine[2], "sensor")
        assert not c._frame_valid(genuine[1], "sensor")                    # older counter than one already accepted
        assert not c._frame_valid(genuine[2], "sensor")                    # exact replay

    def test_ideal_mode_stays_the_default(self):
        assert ChainParams().auth_mode == "ideal" and ChainParams().mac_bits == 24
