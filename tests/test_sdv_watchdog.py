"""
tests/test_sdv_watchdog.py — the authentication + silence watchdog on synthetic captures (no dataset needed).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from sdv.realdata.road import merge_events
from sdv.realdata.watchdog import SilenceWatchdog

HZ, SECONDS = 100, 60


def stream(can_id, hz=HZ, seconds=SECONDS, jitter=0.0002, seed=0):
    rng = np.random.default_rng(seed + can_id)
    t = np.arange(0, seconds, 1.0 / hz) + rng.normal(0, jitter, int(seconds * hz))
    return np.sort(t), np.full(len(t), can_id, dtype=np.int32)


def capture(parts):
    t = np.concatenate([p[0] for p in parts])
    ids = np.concatenate([p[1] for p in parts])
    order = np.argsort(t, kind="stable")
    return t[order], ids[order]


@pytest.fixture(scope="module")
def watchdog():
    normal = [capture([stream(100, seed=s), stream(200, hz=20, seed=s)]) for s in range(3)]
    return SilenceWatchdog(k=3.0, min_s=0.03).learn(normal)


class TestLearning:

    def test_periods_are_the_median_gaps(self, watchdog):
        assert watchdog.period[100] == pytest.approx(0.01, rel=0.05)
        assert watchdog.period[200] == pytest.approx(0.05, rel=0.05)

    def test_a_few_long_gaps_do_not_disqualify_an_id(self):
        t, ids = stream(100)
        keep = ~((t > 20) & (t < 22))                  # a 2 s dropout in an otherwise regular stream
        wd = SilenceWatchdog().learn([(t[keep], ids[keep])])
        assert 100 in wd.period

    def test_an_irregular_id_is_not_watched(self):
        rng = np.random.default_rng(1)
        t = np.sort(rng.uniform(0, 60, 2000))
        wd = SilenceWatchdog().learn([(t, np.full(len(t), 300, dtype=np.int32))])
        assert 300 not in wd.period

    def test_too_few_frames_are_not_enough(self):
        t, ids = stream(100, seconds=0.5)
        assert 100 not in SilenceWatchdog(min_frames=100).learn([(t, ids)]).period

    def test_the_threshold_has_a_floor(self, watchdog):
        assert watchdog.threshold(100) == pytest.approx(0.03)            # 3 x 10 ms, equal to the floor
        assert SilenceWatchdog(k=2.0, min_s=0.03).learn([stream(100)]).threshold(100) == pytest.approx(0.03)
        assert watchdog.threshold(200) == pytest.approx(0.15, rel=0.05)


class TestDetection:

    def test_normal_traffic_raises_no_alarm(self, watchdog):
        t, ids = capture([stream(100, seed=9), stream(200, hz=20, seed=9)])
        assert len(watchdog.alarms(t, ids)) == 0

    def test_replaced_frames_are_noticed_within_k_periods_once_authenticated(self, watchdog):
        t, ids = capture([stream(100, seed=5), stream(200, hz=20, seed=5)])
        forged = (ids == 100) & (t >= 20) & (t < 30)                      # same rate, forged payloads
        alarms = watchdog.alarms(t, ids, accepted=~forged)
        assert len(alarms) >= 1
        assert 20.0 <= alarms.min() <= 20.0 + watchdog.threshold(100) + 0.01

    def test_without_authentication_replacement_is_invisible(self, watchdog):
        t, ids = capture([stream(100, seed=5), stream(200, hz=20, seed=5)])
        assert len(watchdog.alarms(t, ids)) == 0                          # frames keep arriving, nobody rejects them

    def test_injected_extra_frames_do_not_silence_the_genuine_stream(self, watchdog):
        genuine = capture([stream(100, seed=5), stream(200, hz=20, seed=5)])
        extra_t = np.arange(20, 30, 0.003)
        t, ids = capture([genuine, (extra_t, np.full(len(extra_t), 100, dtype=np.int32))])
        forged = np.zeros(len(t), dtype=bool)
        forged[np.isin(t, extra_t)] = True
        assert len(watchdog.alarms(t, ids, accepted=~forged)) == 0         # extras rejected, genuine frames continue

    def test_an_id_that_stops_for_good_is_noticed(self, watchdog):
        t, ids = capture([stream(100, seed=5), stream(200, hz=20, seed=5)])
        keep = ~((ids == 200) & (t > 40))
        alarms = watchdog.alarms(t[keep], ids[keep])
        assert len(alarms) == 1 and alarms[0] == pytest.approx(40.0 + watchdog.threshold(200), abs=0.1)

    def test_a_larger_k_delays_the_alarm(self):
        normal = [capture([stream(100, seed=s)]) for s in range(2)]
        t, ids = stream(100, seed=5)
        keep = ~((t >= 20) & (t < 30))
        first = {k: SilenceWatchdog(k=k, min_s=0.0).learn(normal).alarms(t[keep], ids[keep]).min() for k in (2.0, 5.0)}
        assert first[5.0] - first[2.0] == pytest.approx(0.03, abs=0.005)

    def test_events_merge_for_counting(self, watchdog):
        t, ids = stream(100, seed=5)
        keep = ~(((t >= 10) & (t < 10.5)) | ((t >= 30) & (t < 30.5)))
        assert len(merge_events(watchdog.alarms(t[keep], ids[keep]))) == 2
