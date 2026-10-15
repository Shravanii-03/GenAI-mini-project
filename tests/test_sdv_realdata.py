"""
tests/test_sdv_realdata.py — ROAD loader and semantics-free detectors on synthetic captures
(no dataset needed; the real-data experiment itself is experiments/e8_road_validation.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.realdata.detectors import JumpRule, PairRule, RangeRule, RateIDS, learn_jumps, learn_pairs, learn_ranges
from sdv.realdata.road import N_SIGNALS, Capture, load_raw_log, load_signal_csv, merge_events

RNG = np.random.default_rng(0)
SECONDS, HZ = 60, 50


def make_capture(name="c", attack=None, replace=True, seed=0):
    """ID 100 carries a speed-like signal; ID 200 carries a redundant copy (2*x+3); ID 300 a noisy one."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, SECONDS, 1 / HZ)
    speed = 40 + 25 * np.sin(t / 7) + rng.normal(0, 0.05, len(t))
    rows = []
    for i, ti in enumerate(t):
        copy = 2 * speed[i] + 3 + rng.normal(0, 0.05)
        if attack and attack[0] <= ti <= attack[1]:
            copy += 60.0                                   # forged value, same frame rate
            if not replace:
                rows.append((ti + 0.0001, 200, 0, copy, 1))   # injected extra frame
                copy = 2 * speed[i] + 3
        rows.append((ti, 100, 0, speed[i], 0))
        rows.append((ti, 200, 0, copy, 1 if attack and attack[0] <= ti <= attack[1] and replace else 0))
        rows.append((ti, 300, 0, rng.normal(0, 1), 0))
    rows.sort(key=lambda r: r[0])
    vals = np.full((len(rows), N_SIGNALS), np.nan, dtype=np.float32)
    for n, r in enumerate(rows):
        vals[n, 0] = r[3]
    return Capture(name, np.array([r[0] for r in rows]), np.array([r[1] for r in rows], dtype=np.int32),
                   vals, np.array([r[4] for r in rows], dtype=np.int8))


@pytest.fixture(scope="module")
def normal():
    return [make_capture(f"n{i}", seed=i) for i in range(3)]


class TestCapture:

    def test_series_and_keys(self, normal):
        cap = normal[0]
        assert {i for i, _ in cap.signal_keys()} == {100, 200, 300}
        t, v = cap.series(100, 0)
        assert len(t) == len(v) == SECONDS * HZ and cap.duration == pytest.approx(SECONDS, abs=0.1)

    def test_unknown_id_gives_empty_series(self, normal):
        assert len(normal[0].series(999, 0)[0]) == 0


class TestRules:

    def test_range_rule_flags_values_outside_normal(self, normal):
        rules = {r.can_id: r for r in learn_ranges(normal)}
        attacked = make_capture("a", attack=(20, 30))
        assert len(rules[200].alarms(attacked)) > 0 and len(rules[200].alarms(normal[0])) == 0

    def test_jump_rule_flags_a_step(self, normal):
        rules = {r.can_id: r for r in learn_jumps(normal)}
        attacked = make_capture("a", attack=(20, 30))
        times = rules[200].alarms(attacked)
        assert len(times) >= 1 and 19.9 <= times[0] <= 20.2          # fires at the step, not before

    def test_pair_rule_finds_the_redundant_signals(self, normal):
        pairs = learn_pairs(normal, r_min=0.99)
        keyed = {frozenset([p.a[0], p.b[0]]) for p in pairs}
        assert frozenset([100, 200]) in keyed

    def test_pair_rule_catches_a_consistent_in_rate_forgery_and_stays_quiet_on_normal_data(self, normal):
        rule = next(p for p in learn_pairs(normal, r_min=0.99) if {p.a[0], p.b[0]} == {100, 200})
        attacked = make_capture("a", attack=(20, 30))
        times = rule.alarms(attacked)
        assert len(times) > 0 and times.min() >= 19.9 and times.max() <= 30.1
        assert len(rule.alarms(make_capture("fresh", seed=9))) == 0

    def test_pair_rule_with_exact_relation(self):
        rule = PairRule((100, 0), (200, 0), slope=2.0, intercept=3.0, tol=1.0)
        assert len(rule.alarms(make_capture("ok", seed=3))) == 0

    def test_rule_dataclasses_are_hashable_values(self):
        assert RangeRule(1, 0, 0.0, 1.0) == RangeRule(1, 0, 0.0, 1.0)
        assert JumpRule(1, 0, 2.0).kind == "jump"


class TestRateIDS:

    def learn(self, normal):
        return RateIDS(min_frames=50).learn([(c.t, c.ids) for c in normal])

    def test_periodic_ids_are_learned(self, normal):
        ids = self.learn(normal)
        assert set(ids.period) >= {100, 200, 300} and ids.period[100] == pytest.approx(1 / HZ, rel=0.05)

    def test_replacing_frames_keeps_the_rate_so_the_rate_ids_is_blind(self, normal):
        ids = self.learn(normal)
        attacked = make_capture("masq", attack=(20, 30), replace=True)
        assert len(ids.alarms(attacked.t, attacked.ids)) == 0

    def test_injecting_extra_frames_is_caught(self, normal):
        ids = self.learn(normal)
        fabricated = make_capture("fab", attack=(20, 30), replace=False)
        alarms = ids.alarms(fabricated.t, fabricated.ids)
        assert len(alarms) > 0 and 19.9 <= alarms.min() <= 20.2

    def test_normal_data_does_not_alarm(self, normal):
        ids = self.learn(normal)
        fresh = make_capture("fresh", seed=11)
        assert len(ids.alarms(fresh.t, fresh.ids)) == 0

    def test_a_silent_id_is_caught(self, normal):
        ids = self.learn(normal)
        cap = make_capture("silent", seed=12)
        keep = ~((cap.ids == 100) & (cap.t > 30) & (cap.t < 40))
        assert len(ids.alarms(cap.t[keep], cap.ids[keep])) > 0


class TestIO:

    def test_events_merge_alarms_that_are_close_together(self):
        assert merge_events([1.0, 1.2, 1.5, 5.0, 5.1, 9.0], gap=1.0) == [1.0, 5.0, 9.0]
        assert merge_events([]) == []

    def test_signal_csv_round_trip_with_cache(self, tmp_path):
        header = "Label,Time,ID," + ",".join(f"Signal_{i}_of_ID" for i in range(1, N_SIGNALS + 1))
        rows = [f"0,{t / 100:.3f},{100 + t % 2}," + ",".join([f"{t * 1.5}"] + [""] * (N_SIGNALS - 1)) for t in range(10)]
        path = tmp_path / "cap.csv"
        path.write_text(header + "\n" + "\n".join(rows) + "\n")
        cap = load_signal_csv(path, cache_dir=tmp_path / "cache")
        assert len(cap.t) == 10 and cap.vals.shape == (10, N_SIGNALS) and np.isnan(cap.vals[0, 1])
        again = load_signal_csv(path, cache_dir=tmp_path / "cache")
        assert np.array_equal(again.ids, cap.ids) and (tmp_path / "cache").exists()

    def test_raw_log_parser_reads_candump_lines(self, tmp_path):
        path = tmp_path / "x.log"
        path.write_text("(1110000000.000000) can0 354#1FFF40000003E380\n"
                        "(1110000000.500000) can0 0D0#0011223344556677\n"
                        "garbage line\n")
        t, ids = load_raw_log(path)
        assert list(ids) == [0x354, 0x0D0] and t[1] == pytest.approx(0.5)
