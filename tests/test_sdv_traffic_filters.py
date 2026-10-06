"""
tests/test_sdv_traffic_filters.py — bus tx filters, background traffic, TTC trigger.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.bus.can_bus import CanBus
from sdv.runner import run_once
from sdv.schemas import CanFrame, Scenario
from sdv.sim.engine import Simulator
from sdv.system.brake_chain import CHAIN_IDS, BrakeChain
from sdv.traffic.background import BackgroundTraffic, load_periodic_messages


class TestTxFilters:

    def test_filter_can_drop_a_frame(self):
        sim = Simulator()
        bus = CanBus(sim)
        bus.add_tx_filter(lambda f, now: (None, 0) if f.can_id == 0x100 else (f, 0))
        got = []
        bus.subscribe(lambda f: got.append(f.can_id))
        bus.send(CanFrame(can_id=0x100, src="a"))
        bus.send(CanFrame(can_id=0x200, src="b"))
        sim.run()
        assert got == [0x200]
        assert [f.can_id for f in bus.dropped] == [0x100]

    def test_filter_can_delay_a_frame(self):
        sim = Simulator()
        bus = CanBus(sim)
        bus.add_tx_filter(lambda f, now: (f, 5000))
        f = CanFrame(can_id=0x100, src="a")
        bus.send(f)
        sim.run()
        assert f.t_enqueued_us == 5000
        assert f.t_rx_us == 5000 + bus.tx_time_us(8)

    def test_filter_can_modify_a_frame(self):
        sim = Simulator()
        bus = CanBus(sim)

        def bias(frame, now):
            frame.data["distance_m"] += 10
            return frame, 0

        bus.add_tx_filter(bias)
        got = []
        bus.subscribe(got.append)
        bus.send(CanFrame(can_id=0x100, src="a", data={"distance_m": 5.0}))
        sim.run()
        assert got[0].data["distance_m"] == 15.0


class TestBackgroundTraffic:

    def test_catalog_messages_are_periodic_and_classical_can(self):
        msgs = load_periodic_messages(exclude_ids=CHAIN_IDS)
        assert len(msgs) >= 8
        assert all(m["dlc"] <= 8 and m["cycle_us"] > 0 for m in msgs)
        assert not {m["id"] for m in msgs} & set(CHAIN_IDS)

    def test_frames_arrive_at_their_cycle_time(self):
        sim = Simulator()
        bus = CanBus(sim)
        BackgroundTraffic(sim, bus, random.Random(1), CHAIN_IDS, jitter=0.0).start()
        sim.run(until_us=1_000_000)
        speed = [f.t_enqueued_us for f in bus.log if f.can_id == 0x200]
        gaps = {b - a for a, b in zip(speed, speed[1:])}
        assert gaps == {10_000}

    def test_background_load_is_realistic(self):
        sim = Simulator()
        bus = CanBus(sim)
        BackgroundTraffic(sim, bus, random.Random(2), CHAIN_IDS).start()
        sim.run(until_us=1_000_000)
        assert 0.05 < bus.utilisation(1_000_000) < 0.30


class TestTtcTrigger:

    def test_far_obstacle_delays_braking_until_ttc_threshold(self):
        near = run_once(Scenario(v0_kmh=60, d0_m=25), seed=5)
        far = run_once(Scenario(v0_kmh=60, d0_m=60), seed=5)   # TTC 3.6 s > 2 s trigger
        assert far.e2e_latency_ms > near.e2e_latency_ms + 1000

    def test_chain_ignores_frames_when_ttc_above_trigger(self):
        chain = BrakeChain(Scenario(v0_kmh=60, d0_m=60), seed=1)
        chain.run()
        assert chain.timeline["sensor_rx"] > chain.t_appear_us + 1_000_000

    def test_run_stops_shortly_after_brake_onset(self):
        chain = BrakeChain(Scenario(), seed=1)
        chain.run()
        assert chain.sim.now <= chain.brake_onset_us + chain.params.tail_ms * 1000 + 1
