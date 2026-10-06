"""
tests/test_sdv_monitors.py — monitors, detection margin and their honesty.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from sdv.attacks.library import make_attack
from sdv.metrics.detection_margin import (
    classify_run, detection_margin_ms, detection_time_ms, f1_from_counts, summarise,
)
from sdv.monitors.monitors import (
    DeadlineMonitor, FrequencyIDS, FusedMonitor, PlausibilityMonitor, observe,
)
from sdv.runner import execute
from sdv.schemas import Scenario

SCEN = Scenario(v0_kmh=60, d0_m=30, cpu_load=0.4)


def run_obs(seed, attacks=(), scenario=SCEN):
    result, chain = execute(scenario, seed, attacks=list(attacks))
    frames, ctx = observe(chain)
    return result, chain, frames, ctx


@pytest.fixture(scope="module")
def monitors():
    train = [run_obs(1000 + i)[2:] for i in range(30)]
    ms = {
        "deadline": DeadlineMonitor(),
        "deadline_oracle": DeadlineMonitor(oracle=True),
        "frequency": FrequencyIDS(),
        "plausibility": PlausibilityMonitor(),
    }
    for m in ms.values():
        m.train(train)
    return ms


def alarm_rate(monitor, attack_factory=None, seeds=range(20)):
    hits = 0
    for s in seeds:
        attacks = [attack_factory()] if attack_factory else []
        _, _, frames, ctx = run_obs(s, attacks)
        hits += monitor.first_alarm_us(frames, ctx) is not None
    return hits / len(list(seeds))


class TestFalseAlarms:

    @pytest.mark.parametrize("name", ["deadline", "deadline_oracle", "frequency", "plausibility"])
    def test_benign_runs_rarely_alarm(self, monitors, name):
        assert alarm_rate(monitors[name]) <= 0.10


class TestDetectionPattern:

    def test_flood_starves_the_sensor_so_only_the_oracle_deadline_monitor_sees_it(self, monitors):
        flood = lambda: make_attack("dos_flood", rate_hz=4000, duration_ms=300, start_offset_ms=-20)
        assert alarm_rate(monitors["frequency"], flood) > 0.9
        assert alarm_rate(monitors["deadline_oracle"], flood) > 0.9
        assert alarm_rate(monitors["deadline"], flood) <= 0.15   # threat is first seen only after the flood

    def test_drift_spoof_is_invisible_to_timing_monitors_but_not_plausibility(self, monitors):
        drift = lambda: make_attack("sensor_drift_spoof", rate_m_per_s=25, duration_ms=800,
                                    start_offset_ms=-400)
        assert alarm_rate(monitors["frequency"], drift) <= 0.15
        assert alarm_rate(monitors["plausibility"], drift) > 0.9

    def test_masquerade_keeps_timing_normal_but_breaks_physics(self, monitors):
        mask = lambda: make_attack("masquerade", bias_m=20, phase_shift_ms=0, duration_ms=800,
                                   start_offset_ms=-400)
        assert alarm_rate(monitors["frequency"], mask) <= 0.15
        assert alarm_rate(monitors["plausibility"], mask) > 0.9

    def test_suppression_breaks_counter_and_period(self, monitors):
        sup = lambda: make_attack("selective_suppression", k=2, duration_ms=500, start_offset_ms=-100)
        assert alarm_rate(monitors["plausibility"], sup) > 0.9
        assert alarm_rate(monitors["frequency"], sup) > 0.5

    def test_upstream_gateway_delay_is_hidden_from_the_deadline_monitor(self, monitors):
        delay = lambda: make_attack("gateway_delay", delay_ms=80, duration_ms=800, start_offset_ms=-100)
        assert alarm_rate(monitors["frequency"], delay) > 0.9
        assert alarm_rate(monitors["deadline"], delay) <= 0.15

    def test_fused_monitor_alarms_at_least_as_often_as_each_part(self, monitors):
        fused = FusedMonitor([monitors["deadline"], monitors["frequency"], monitors["plausibility"]])
        mask = lambda: make_attack("masquerade", bias_m=20, duration_ms=800, start_offset_ms=-400)
        assert alarm_rate(fused, mask) >= alarm_rate(monitors["plausibility"], mask)


class TestHonesty:

    def test_monitors_do_not_depend_on_sender_or_attack_flag(self, monitors):
        _, chain, frames, ctx = run_obs(3, [make_attack("dos_flood", rate_hz=4000, duration_ms=300,
                                                        start_offset_ms=-20)])
        before = {k: m.first_alarm_us(frames, ctx) for k, m in monitors.items()}
        for f in chain.bus.log:
            f.attack = False
            f.src = "nobody"
        frames2, ctx2 = observe(chain)
        after = {k: m.first_alarm_us(frames2, ctx2) for k, m in monitors.items()}
        assert before == after

    def test_observed_frames_expose_only_bus_visible_fields(self):
        _, _, frames, _ = run_obs(1)
        assert frames[0]._fields == ("t_us", "can_id", "dlc", "data")

    def test_thresholds_are_learned_from_benign_data_only(self, monitors):
        assert monitors["deadline"].deadline_ms and monitors["deadline"].deadline_ms < 200
        assert monitors["frequency"].period_us[0x200] == pytest.approx(10_000, rel=0.05)


class TestMargin:

    def make_result(self, safe_ms):
        r, _, _, _ = run_obs(1)
        return r.model_copy(update={"latest_safe_latency_ms": safe_ms})

    def test_margin_is_point_of_no_return_minus_detection_time(self):
        r = self.make_result(120.0)
        assert detection_margin_ms(r, alarm_us=500_000 + 40_000, t_appear_us=500_000) == pytest.approx(80.0)

    def test_response_time_reduces_the_margin(self):
        r = self.make_result(120.0)
        assert detection_margin_ms(r, 540_000, 500_000, response_ms=30) == pytest.approx(50.0)

    def test_no_alarm_gives_minus_infinity(self):
        r = self.make_result(120.0)
        assert detection_margin_ms(r, None, 500_000) == -math.inf
        assert detection_time_ms(None, 500_000) == math.inf

    def test_unavoidable_hazard_has_no_margin(self):
        assert detection_margin_ms(self.make_result(-5.0), 540_000, 500_000) is None

    def test_early_alarm_before_the_threat_gives_a_large_margin(self):
        r = self.make_result(100.0)
        assert detection_margin_ms(r, 400_000, 500_000) == pytest.approx(200.0)

    def test_classification_treats_pre_attack_alarms_as_false(self):
        assert classify_run(600_000, attack_start_us=500_000) == "TP"
        assert classify_run(400_000, attack_start_us=500_000) == "FP"
        assert classify_run(None, attack_start_us=500_000) == "FN"
        assert classify_run(None, None) == "TN"
        assert classify_run(300_000, None) == "FP"

    def test_summary_separates_detection_from_timeliness(self):
        rows = [
            {"outcome": "TP", "hazard": True, "margin_ms": 40.0},
            {"outcome": "TP", "hazard": True, "margin_ms": -30.0},
            {"outcome": "TP", "hazard": False, "margin_ms": None},
            {"outcome": "TN", "hazard": False, "margin_ms": None},
        ]
        s = summarise(rows)
        assert s["recall"] == 1.0 and s["fpr"] == 0.0 and s["f1"] == 1.0
        assert s["timely_rate"] == 0.5 and s["hazard_runs"] == 2

    def test_f1_edge_cases(self):
        assert f1_from_counts(0, 3, 4) == 0.0
        assert f1_from_counts(5, 0, 0) == 1.0
