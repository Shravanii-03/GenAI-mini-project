"""
tests/test_sdv_phase1.py — engine, CAN bus, brake chain and plant model.
Run: pytest tests/ -v
"""
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdv.bus.can_bus import CanBus, frame_bits
from sdv.plant.longitudinal import (
    braking_distance, decel_for_road, latest_safe_latency_s, simulate_braking,
)
from sdv.runner import run_once
from sdv.schemas import CanFrame, Scenario
from sdv.sim.engine import Simulator


class TestEngine:

    def test_events_run_in_time_order_then_scheduling_order(self):
        sim, out = Simulator(), []
        sim.schedule(20, out.append, "c")
        sim.schedule(10, out.append, "a")
        sim.schedule(10, out.append, "b")
        sim.run()
        assert out == ["a", "b", "c"]

    def test_cannot_schedule_in_the_past(self):
        sim = Simulator()
        sim.schedule(10, lambda: None)
        sim.run()
        try:
            sim.schedule_at(5, lambda: None)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestCanBus:

    def test_frame_length_worst_case_stuffing(self):
        assert frame_bits(8) == 135
        assert frame_bits(0) == 47 + (34 - 1) // 4

    def test_transmission_time_at_500kbps(self):
        bus = CanBus(Simulator(), bitrate_bps=500_000)
        assert bus.tx_time_us(8) == 270

    def test_lowest_id_wins_arbitration(self):
        sim = Simulator()
        bus = CanBus(sim)
        order = []
        bus.subscribe(lambda f: order.append(f.can_id))
        bus.send(CanFrame(can_id=0x300, src="a"))
        bus.send(CanFrame(can_id=0x100, src="b"))
        bus.send(CanFrame(can_id=0x200, src="c"))
        sim.run()
        assert order == [0x100, 0x200, 0x300]

    def test_frames_serialise_and_queueing_delays_low_priority(self):
        sim = Simulator()
        bus = CanBus(sim)
        frames = [CanFrame(can_id=0x10 + i, src="x") for i in range(5)]
        victim = CanFrame(can_id=0x7FF, src="victim")
        for f in frames:
            bus.send(f)
        bus.send(victim)
        sim.run()
        assert victim.t_rx_us == 6 * bus.tx_time_us(8)
        assert victim.t_rx_us - victim.t_enqueued_us > 5 * bus.tx_time_us(8)

    def test_idle_bus_delivers_after_one_frame_time(self):
        sim = Simulator()
        bus = CanBus(sim)
        f = CanFrame(can_id=0x1A0, src="x")
        bus.send(f)
        sim.run()
        assert f.t_rx_us - f.t_enqueued_us == bus.tx_time_us(8)


class TestPlant:

    def test_closed_form_matches_textbook_without_ramp(self, monkeypatch):
        v0, a = 20.0, 8.0
        assert math.isclose(braking_distance(v0, a, 0.0), v0 * v0 / (2 * a))

    def test_longer_latency_never_helps(self):
        s = Scenario(v0_kmh=60, d0_m=30, road="dry")
        outcomes = [simulate_braking(s, lat / 1000) for lat in range(0, 400, 20)]
        stops = [o.stop_distance_m for o in outcomes]
        assert stops == sorted(stops)

    def test_point_of_no_return_is_exact_boundary(self):
        s = Scenario(v0_kmh=60, d0_m=30, road="dry")
        v0, a = s.v0_kmh / 3.6, decel_for_road(s.road)
        from sdv.plant.longitudinal import ramp_seconds
        tau = latest_safe_latency_s(v0, s.d0_m, a, ramp_seconds())
        assert tau > 0
        assert not simulate_braking(s, tau - 0.002).collision
        assert simulate_braking(s, tau + 0.002).collision

    def test_never_braking_collides_at_full_speed(self):
        s = Scenario(v0_kmh=72, d0_m=40)
        o = simulate_braking(s, None)
        assert o.collision and math.isclose(o.impact_speed_ms, 20.0)

    def test_collision_reduces_impact_speed_when_braking_helps(self):
        s = Scenario(v0_kmh=60, d0_m=22, road="dry")
        late = simulate_braking(s, 0.30)
        later = simulate_braking(s, 0.60)
        assert late.collision and later.collision
        assert late.impact_speed_ms < later.impact_speed_ms

    def test_worse_road_needs_earlier_braking(self):
        dry = latest_safe_latency_s(16.7, 40, decel_for_road("dry"), 0.05)
        icy = latest_safe_latency_s(16.7, 40, decel_for_road("icy"), 0.05)
        assert icy < dry


class TestBrakeChain:

    def test_same_seed_is_reproducible(self):
        s = Scenario()
        a, b = run_once(s, seed=7), run_once(s, seed=7)
        assert a.e2e_latency_ms == b.e2e_latency_ms
        assert a.timeline_ms == b.timeline_ms

    def test_different_seeds_differ(self):
        s = Scenario()
        lats = {run_once(s, seed=i).e2e_latency_ms for i in range(20)}
        assert len(lats) > 10

    def test_timeline_is_ordered_and_stages_sum_to_latency(self):
        r = run_once(Scenario(), seed=3)
        keys = ["sensor_enq", "sensor_rx", "detect_enq", "detect_rx",
                "cmd_enq", "cmd_rx", "brake_onset"]
        times = [r.timeline_ms[k] for k in keys]
        assert times == sorted(times)
        assert math.isclose(sum(r.stage_ms.values()), r.e2e_latency_ms, abs_tol=1e-6)

    def test_latency_is_not_a_constant_range(self):
        r = run_once(Scenario(cpu_load=0.5), seed=1)
        assert r.braked and r.e2e_latency_ms > 0

    def test_higher_cpu_load_increases_latency(self):
        def mean_latency(load):
            return statistics.mean(
                run_once(Scenario(cpu_load=load), seed=i).e2e_latency_ms for i in range(60)
            )
        assert mean_latency(0.9) > mean_latency(0.5) > mean_latency(0.1)

    def test_margin_sign_matches_collision(self):
        for seed in range(30):
            r = run_once(Scenario(v0_kmh=60, d0_m=26, cpu_load=0.8), seed=seed)
            assert (r.margin_ms < 0) == r.outcome.collision
