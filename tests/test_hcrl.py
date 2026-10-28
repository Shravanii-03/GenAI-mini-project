"""
tests/test_hcrl.py — the HCRL Car-Hacking loader and the E18 helpers, on synthetic data (the real files are not in the repository).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experiments"))

from e18_hcrl_replay import background_of, flood_bound_ms, measured_traffic, worst_gap_overlapping
from sdv.analysis import bounds
from sdv.realdata import hcrl

CSV = [
    "1478198376.389427,0316,8,05,21,68,09,21,21,00,6f,R",
    "1478198376.389636,018f,8,fe,5b,00,00,00,3c,00,00,R",
    "1478198376.389900,0000,8,00,00,00,00,00,00,00,00,T",
    "1478198376.390100,0545,2,d8,00,R",             # short frame: fewer data bytes
    "garbage line",
    "1478198376.391,zzzz,8,00,R",                   # bad id
    "",
]
TEXT = [
    "Timestamp: 1479121434.850202        ID: 0350    000    DLC: 8    05 28 84 66 6d 00 00 a2",
    "Timestamp: 1479121434.850423        ID: 02c0    000    DLC: 8    14 00 00 00 00 00 00 00",
]


def test_csv_lines_parse_and_bad_lines_are_skipped():
    cap = hcrl.parse_lines(CSV)
    assert len(cap.t) == 4 and cap.ids.tolist() == [0x316, 0x18F, 0x0, 0x545]
    assert cap.labels.tolist() == [0, 0, 1, 0] and cap.dlc.tolist() == [8, 8, 8, 2]
    assert cap.t[0] == 0.0 and cap.t[-1] == pytest.approx(0.000673, abs=1e-6)


def test_text_layout_of_the_attack_free_file_parses():
    cap = hcrl.parse_lines(TEXT)
    assert cap.ids.tolist() == [0x350, 0x2C0] and cap.labels.tolist() == [0, 0]


def test_empty_input_is_an_error():
    with pytest.raises(ValueError):
        hcrl.parse_lines(["nothing here"])


def test_bursts_group_injected_frames():
    t = np.r_[np.arange(0, 1, 0.01), np.arange(5, 6, 0.01)]
    cap = hcrl.Capture("x", t, np.zeros(len(t), np.int32), np.full(len(t), 8, np.int8), np.ones(len(t), np.int8))
    assert hcrl.bursts(cap) == [(0.0, pytest.approx(0.99)), (5.0, pytest.approx(5.99))]
    cap.labels[:] = 0
    assert hcrl.bursts(cap) == []


def test_cache_round_trip(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("\n".join(CSV), encoding="utf-8")
    first = hcrl.load_cached(path, tmp_path / "cache")
    second = hcrl.load_cached(path, tmp_path / "cache")
    assert (tmp_path / "cache" / "x.npz").exists()
    assert first.ids.tolist() == second.ids.tolist() and first.labels.tolist() == second.labels.tolist()


def synthetic_vehicle(seconds=20.0):
    """Two periodic IDs (10 ms and 100 ms) with a little jitter."""
    rng = np.random.default_rng(1)
    t, ids = [], []
    for can_id, period in ((0x100, 0.010), (0x200, 0.100)):
        times = np.arange(0, seconds, period) + rng.normal(0, 0.0002, int(seconds / period))
        t.append(times)
        ids.append(np.full(len(times), can_id))
    t, ids = np.concatenate(t), np.concatenate(ids)
    order = np.argsort(t)
    t, ids = t[order] - t.min(), ids[order]
    return hcrl.Capture("v", t, ids.astype(np.int32), np.full(len(t), 8, np.int8), np.zeros(len(t), np.int8))


def test_measured_traffic_recovers_periods():
    traffic = measured_traffic(synthetic_vehicle())
    assert traffic[0x100]["period_s"] == pytest.approx(0.010, rel=0.02)
    assert traffic[0x200]["period_s"] == pytest.approx(0.100, rel=0.02) or 0x200 not in traffic


def test_background_override_is_applied_and_restored():
    traffic = {0x100: {"period_s": 0.01, "jitter_s": 0.0, "dlc": 8, "max_gap_s": 0.011}}
    original = bounds._background
    with background_of(traffic):
        assert [s.can_id for s in bounds._background()] == [0x100]
    assert bounds._background is original


def test_a_faster_flood_never_gives_a_smaller_bound():
    traffic = {0x100: {"period_s": 0.01, "jitter_s": 0.0, "dlc": 8, "max_gap_s": 0.011},
               0x200: {"period_s": 0.02, "jitter_s": 0.0, "dlc": 8, "max_gap_s": 0.021}}
    slow = flood_bound_ms(0x200, traffic, 0.002, 1.0)
    fast = flood_bound_ms(0x200, traffic, 0.0005, 1.0)
    saturating = flood_bound_ms(0x200, traffic, bounds._c_us(8) / 1e6, 1.0)
    assert slow <= fast <= saturating
    assert saturating > 900                      # a saturating flood blocks for about the burst length


def test_worst_gap_overlapping_window():
    t = np.array([0.0, 0.1, 0.2, 1.4, 1.5, 1.6])
    assert worst_gap_overlapping(t, 0.5, 1.0) == pytest.approx(1.2)      # the long gap spans the window
    assert worst_gap_overlapping(t, 1.45, 1.55) == pytest.approx(0.1)
    assert worst_gap_overlapping(np.array([1.0]), 0, 2) is None
