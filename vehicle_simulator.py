"""
vehicle_simulator.py
====================
Real-time Vehicle Signal Simulator for SDV Safety & Threat Detection System.

Generates realistic VSS (COVESA Vehicle Signal Specification) and CAN bus signals
every 50ms, simulating complete driving scenarios:
  - Normal driving → obstacle → emergency braking → resume
  - Pedestrian detection
  - Lane departure
  - Cruise control

Outputs frames as plain dicts compatible with:
  - attack_injector.inject(frame)       needs: speed, delay_ms
  - realtime_monitor / main_pipeline    needs: delay_ms, mode, road_condition, cpu_load, event_chain
  - dashboard streaming                 full VSS signals

Signal names follow official COVESA VSS 4.0 standard.
"""

import json
import time
import random
import threading
import queue
import logging
from enum import Enum


logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIMULATOR] %(levelname)s  %(message)s")
log = logging.getLogger("vehicle_simulator")


class DrivingPhase(Enum):
    STARTUP          = "startup"
    NORMAL_DRIVING   = "normal_driving"
    OBSTACLE_AHEAD   = "obstacle_ahead"
    EMERGENCY_BRAKE  = "emergency_brake"
    POST_BRAKE       = "post_brake"
    PEDESTRIAN       = "pedestrian_detected"
    LANE_DEPARTURE   = "lane_departure"
    CRUISE           = "cruise_control"
    STOPPED          = "stopped"


ASIL_LIMITS = {"ASIL-D": 100, "ASIL-C": 150, "ASIL-B": 200, "ASIL-A": 500}

CAN_IDS = {"BRAKE_CMD": 0x1A0, "ENGINE_CTRL": 0x0B0, "ADAS_CTRL": 0x3C0, "SPEED_SENSOR": 0x4D0}

# (phase, duration_ticks @50ms, target_speed_kmh, description)
SCENARIOS = [
    (DrivingPhase.STARTUP,        20,   0,  "Engine start, idle"),
    (DrivingPhase.NORMAL_DRIVING, 60,  60,  "Accelerating to 60 km/h"),
    (DrivingPhase.CRUISE,         40,  60,  "Cruising at 60 km/h"),
    (DrivingPhase.NORMAL_DRIVING, 40,  80,  "Accelerating to 80 km/h"),
    (DrivingPhase.CRUISE,         30,  80,  "Cruising at 80 km/h"),
    (DrivingPhase.LANE_DEPARTURE, 20,  78,  "Lane departure warning"),
    (DrivingPhase.CRUISE,         20,  80,  "Lane correction"),
    (DrivingPhase.PEDESTRIAN,     30,  40,  "Pedestrian detected"),
    (DrivingPhase.CRUISE,         20,  40,  "Post-pedestrian cruise"),
    (DrivingPhase.OBSTACLE_AHEAD, 25,  30,  "Obstacle ahead"),
    (DrivingPhase.EMERGENCY_BRAKE,20,   0,  "Emergency brake"),
    (DrivingPhase.POST_BRAKE,     30,  30,  "Resuming after obstacle"),
    (DrivingPhase.NORMAL_DRIVING, 50,  70,  "Back to normal"),
    (DrivingPhase.OBSTACLE_AHEAD, 20,  20,  "Second obstacle"),
    (DrivingPhase.EMERGENCY_BRAKE,25,   0,  "Second emergency brake"),
    (DrivingPhase.STOPPED,        20,   0,  "Stopped"),
]


def _noise(v, pct=0.02):
    return v + random.gauss(0, abs(v) * pct + 0.001)

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _rpm(speed, throttle):
    gear = max(1, min(6, int(speed / 25) + 1))
    return _clamp(800 + (speed / gear) * 35 + throttle * 10, 800, 7000)

def _ttc(dist, closing_kmh):
    return round(dist / (closing_kmh / 3.6), 2) if closing_kmh > 0 else 999.0


class VehicleSimulator:
    """
    Usage (threaded):
        sim = VehicleSimulator(); sim.start()
        frame = sim.get_frame()   # dict

    Usage (manual / old pipeline):
        sim = VehicleSimulator()
        frame = sim.tick()          # or sim.generate_frame()
    """

    def __init__(self, tick_interval_ms=50, output_queue=None,
                 loop_scenarios=True, log_to_file=False, log_file="simulation_frames.jsonl"):
        self.tick_s        = tick_interval_ms / 1000.0
        self.output_queue  = output_queue or queue.Queue(maxsize=200)
        self.loop_scenarios= loop_scenarios
        self.log_to_file   = log_to_file
        self.log_file      = log_file
        self._running      = threading.Event()
        self._thread       = None
        self._fh           = None
        self._reset_state()

    def _reset_state(self):
        self.phase           = DrivingPhase.STARTUP
        self.phase_tick      = 0
        self.frame_id        = 0
        self.scenario_index  = 0
        self.start_time      = time.time()
        self.speed_kmh       = 0.0
        self.target_speed    = 0.0
        self.accel_ms2       = 0.0
        self.throttle_pct    = 0.0
        self.brake_pct       = 0.0
        self.steering_deg    = 0.0
        self.engine_rpm      = 800.0
        self.obstacle_dist   = 999.0
        self.obstacle_speed  = 0.0
        self.pedestrian_dist = 999.0
        self.lane_offset     = 0.0
        self.brake_event_start = None
        self.brake_response_ms = 0.0
        self.brake_applied   = False
        self.cpu_load        = random.uniform(30, 55)

    # ── Threaded mode ──────────────────────────────────────────────────────────
    def start(self):
        self._running.set()
        if self.log_to_file:
            self._fh = open(self.log_file, "w")
        self._thread = threading.Thread(target=self._loop, daemon=True, name="VehicleSim")
        self._thread.start()
        log.info(f"Simulator started (threaded, tick={int(self.tick_s*1000)}ms)")

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._fh:
            self._fh.close()

    def get_frame(self, timeout=1.0):
        try:
            return self.output_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_running(self):
        return self._running.is_set()

    def _loop(self):
        while self._running.is_set():
            t0 = time.perf_counter()
            frame = self._next_frame()
            self._push(frame)
            sleep = self.tick_s - (time.perf_counter() - t0)
            if sleep > 0:
                time.sleep(sleep)

    # ── Manual tick (backward compat with realtime_monitor / main_pipeline) ────
    def tick(self):
        return self._next_frame()

    def generate_frame(self):
        return self._next_frame()

    # ── Core ───────────────────────────────────────────────────────────────────
    def _next_frame(self):
        self._advance_scenario()
        self._update_physics()
        frame = self._build_frame()
        self.frame_id   += 1
        self.phase_tick += 1
        return frame

    def _advance_scenario(self):
        phase, duration, target, desc = SCENARIOS[self.scenario_index]
        if self.phase != phase:
            self.phase = phase; self.phase_tick = 0
            self.target_speed = float(target)
            self._on_enter(phase)
        if self.phase_tick >= duration:
            self.scenario_index += 1
            if self.scenario_index >= len(SCENARIOS):
                if self.loop_scenarios:
                    self.scenario_index = 2
                    log.info("Scenario loop restarted.")
                else:
                    self._running.clear(); return
            phase, _, target, desc = SCENARIOS[self.scenario_index]
            self.phase = phase; self.phase_tick = 0
            self.target_speed = float(target)
            log.info(f"Phase → {phase.value}  ({desc})")
            self._on_enter(phase)

    def _on_enter(self, phase):
        if phase == DrivingPhase.OBSTACLE_AHEAD:
            self.obstacle_dist = random.uniform(25, 45)
            self.obstacle_speed= random.uniform(10, 20)
            self.brake_event_start = None; self.brake_applied = False
        elif phase == DrivingPhase.EMERGENCY_BRAKE:
            self.brake_event_start = time.time(); self.brake_applied = False
        elif phase == DrivingPhase.PEDESTRIAN:
            self.pedestrian_dist = random.uniform(15, 30)
        elif phase == DrivingPhase.LANE_DEPARTURE:
            self.lane_offset = random.choice([-1,1]) * random.uniform(0.3, 0.6)
        elif phase in (DrivingPhase.POST_BRAKE, DrivingPhase.CRUISE, DrivingPhase.NORMAL_DRIVING):
            self.obstacle_dist = 999.0; self.pedestrian_dist = 999.0; self.lane_offset = 0.0
        self.cpu_load = {
            DrivingPhase.EMERGENCY_BRAKE: random.uniform(70, 90),
            DrivingPhase.OBSTACLE_AHEAD:  random.uniform(60, 80),
            DrivingPhase.PEDESTRIAN:      random.uniform(55, 75),
        }.get(phase, random.uniform(30, 55))

    def _update_physics(self):
        dt = self.tick_s
        p  = self.phase
        e  = self.target_speed - self.speed_kmh

        if p == DrivingPhase.STARTUP:
            self.throttle_pct = 0; self.brake_pct = 0; self.accel_ms2 = 0
        elif p in (DrivingPhase.NORMAL_DRIVING, DrivingPhase.CRUISE):
            if e > 2:
                self.throttle_pct = _clamp(e*1.5,5,60); self.brake_pct=0; self.accel_ms2=_clamp(e*0.05,0,3.5)
            elif e < -2:
                self.throttle_pct=0; self.brake_pct=_clamp(abs(e)*0.8,0,20); self.accel_ms2=_clamp(e*0.04,-2,0)
            else:
                self.throttle_pct=20+random.gauss(0,1); self.brake_pct=0; self.accel_ms2=random.gauss(0,0.05)
        elif p == DrivingPhase.OBSTACLE_AHEAD:
            d = _clamp(1-(self.obstacle_dist/50),0,1)
            self.throttle_pct=_clamp(20*(1-d),0,20); self.brake_pct=_clamp(d*60,0,60); self.accel_ms2=_clamp(-d*4,-5,0)
            self.obstacle_dist = max(0, self.obstacle_dist - (self.speed_kmh-self.obstacle_speed)/3.6*dt)
        elif p == DrivingPhase.EMERGENCY_BRAKE:
            self.throttle_pct=0; self.brake_pct=100; self.accel_ms2=-8.0
            if not self.brake_applied and self.brake_pct > 50:
                self.brake_applied = True
                if self.brake_event_start:
                    self.brake_response_ms = (time.time()-self.brake_event_start)*1000
        elif p == DrivingPhase.POST_BRAKE:
            self.throttle_pct=_clamp(e*1.2,0,40); self.brake_pct=0; self.accel_ms2=_clamp(e*0.04,0,2)
        elif p == DrivingPhase.PEDESTRIAN:
            self.throttle_pct=_clamp(e*0.8,0,30); self.brake_pct=_clamp(-e*0.5,0,50); self.accel_ms2=_clamp(e*0.03,-3,1)
            self.pedestrian_dist = max(0, self.pedestrian_dist-(self.speed_kmh/3.6)*dt)
        elif p == DrivingPhase.LANE_DEPARTURE:
            self.steering_deg=_clamp(-self.lane_offset*15,-20,20); self.lane_offset*=0.95; self.throttle_pct=20; self.brake_pct=0
        elif p == DrivingPhase.STOPPED:
            self.throttle_pct=0; self.brake_pct=30; self.accel_ms2=0

        self.speed_kmh  = _clamp(self.speed_kmh + self.accel_ms2*dt*3.6, 0, 200)
        self.engine_rpm = _rpm(self.speed_kmh, self.throttle_pct)
        if p in (DrivingPhase.NORMAL_DRIVING, DrivingPhase.CRUISE):
            self.steering_deg = self.steering_deg*0.9 + random.gauss(0, 0.3)

    def _build_event_chain(self):
        p  = self.phase
        cf = 1.0 + (self.cpu_load - 50) / 200.0   # 0.75–1.225

        # Deltas chosen so total = cumulative sum of all steps:
        # normal/cruise   → 8+10+12+8  = 38ms base → ~35-65ms with noise  (✅ under 100ms)
        # obstacle_ahead  → 8+15+20+15 = 58ms base → ~55-80ms             (✅ under 100ms)
        # pedestrian      → 10+18+22+12= 62ms base → ~58-85ms             (✅ under 100ms)
        # emergency_brake → 12+22+35+28=97ms base  → ~90-130ms            (⚠️ near/over limit)
        # lane_departure  → 8+12+15+10 = 45ms base → ~40-70ms             (✅ under 100ms)
        base = {
            DrivingPhase.EMERGENCY_BRAKE: [("sense",12),("detect",22),("decide",35),("actuate",28)],
            DrivingPhase.OBSTACLE_AHEAD:  [("sense", 8),("detect",15),("decide",20),("actuate",15)],
            DrivingPhase.PEDESTRIAN:      [("sense",10),("detect",18),("decide",22),("actuate",12)],
            DrivingPhase.LANE_DEPARTURE:  [("sense", 8),("detect",12),("decide",15),("actuate",10)],
        }.get(p, [("sense",8),("detect",10),("decide",12),("actuate",8)])   # normal/cruise/startup

        cum = 0; result = []
        for step, delta in base:
            # Emergency brake gets more noise (stressed system)
            noise_std = 4 if p == DrivingPhase.EMERGENCY_BRAKE else 1.5
            cum += max(1, int(delta * cf + random.gauss(0, noise_std)))
            result.append({"step": step, "time_ms": cum})
        return result

    def _build_frame(self):
        p   = self.phase
        ts  = int((time.time() - self.start_time) * 1000)

        obstacle_active  = p in (DrivingPhase.OBSTACLE_AHEAD, DrivingPhase.EMERGENCY_BRAKE)
        pedestrian_active= p == DrivingPhase.PEDESTRIAN
        aeb_active       = p == DrivingPhase.EMERGENCY_BRAKE and self.speed_kmh > 5
        lane_warn        = p == DrivingPhase.LANE_DEPARTURE and abs(self.lane_offset) > 0.25

        closing = max(0.0, self.speed_kmh-self.obstacle_speed) if obstacle_active else 0.0
        ttc     = _ttc(self.obstacle_dist, closing)

        # ISO 26262 check
        iso_viol  = False; iso_type = "none"; iso_rule = ""; safety_state = "nominal"
        if p == DrivingPhase.EMERGENCY_BRAKE and self.brake_applied:
            if self.brake_response_ms > ASIL_LIMITS["ASIL-D"]:
                iso_viol = True
                iso_type = f"BRAKE_RESPONSE_EXCEEDED ({self.brake_response_ms:.1f}ms > 100ms)"
                iso_rule = "ISO26262-6-8.4.5:ASIL-D:BRAKE-100MS"
                safety_state = "critical"
        if obstacle_active and ttc < 1.5 and self.brake_pct < 5:
            iso_viol = True
            iso_type = f"AEB_NOT_TRIGGERED (TTC={ttc:.2f}s)"
            iso_rule = "ISO26262-5-9.4.3:ASIL-C:AEB-ACTIVATION"
            safety_state = "degraded"

        event_chain = self._build_event_chain()
        delay_ms    = sum(e["time_ms"] for e in event_chain)

        road_condition = {
            DrivingPhase.EMERGENCY_BRAKE: random.choice(["wet","icy","dry"]),
            DrivingPhase.OBSTACLE_AHEAD:  random.choice(["wet","dry"]),
        }.get(p, "dry")

        return {
            # ── attack_injector needs these ──────────────────────────────
            "speed":                    round(_noise(self.speed_kmh, 0.01), 2),
            "delay_ms":                 delay_ms,
            # ── realtime_monitor / main_pipeline needs these ─────────────
            "mode":                     p.value,
            "road_condition":           road_condition,
            "cpu_load":                 round(self.cpu_load, 1),
            "event_chain":              event_chain,
            # ── Full VSS signals (dashboard) ─────────────────────────────
            "timestamp_ms":             ts,
            "frame_id":                 self.frame_id,
            "driving_phase":            p.value,
            "vehicle_speed":            round(_noise(self.speed_kmh, 0.01), 2),
            "vehicle_acceleration":     round(_noise(self.accel_ms2, 0.02), 3),
            "engine_rpm":               round(_noise(self.engine_rpm, 0.01)),
            "throttle_position":        round(_clamp(_noise(self.throttle_pct, 0.02), 0, 100), 1),
            "brake_pedal_position":     round(_clamp(_noise(self.brake_pct, 0.02), 0, 100), 1),
            "brake_is_active":          self.brake_pct > 5,
            "brake_fluid_pressure":     round(self.brake_pct * 2.0, 2),
            "brake_response_time_ms":   round(self.brake_response_ms, 2),
            "brake_asil_limit_ms":      ASIL_LIMITS["ASIL-D"],
            "steering_angle":           round(_noise(self.steering_deg, 0.01), 2),
            "obstacle_detected":        obstacle_active,
            "obstacle_distance_m":      round(_noise(self.obstacle_dist, 0.01), 2),
            "obstacle_relative_speed":  round(closing, 2),
            "ttc_seconds":              ttc,
            "pedestrian_detected":      pedestrian_active,
            "pedestrian_distance_m":    round(self.pedestrian_dist, 2) if pedestrian_active else 999.0,
            "lane_departure_warning":   lane_warn,
            "lane_offset_m":            round(self.lane_offset, 3),
            "aeb_active":               aeb_active,
            "can_brake_cmd":            f"0x{CAN_IDS['BRAKE_CMD']:03X}",
            "can_frame_counter":        self.frame_id,
            "can_bus_load_pct":         round(_clamp(15+self.speed_kmh*0.1+random.gauss(0,1.5),5,95),1),
            "iso_violation_detected":   iso_viol,
            "iso_violation_type":       iso_type,
            "iso_rule_id":              iso_rule,
            "asil_level":               "ASIL-D",
            "safety_state":             safety_state,
            "attack":                   {"active": False},
        }

    def _push(self, frame):
        try:
            self.output_queue.put_nowait(frame)
        except queue.Full:
            try: self.output_queue.get_nowait()
            except queue.Empty: pass
            self.output_queue.put_nowait(frame)
        if self.log_to_file and self._fh:
            self._fh.write(json.dumps(frame)+"\n"); self._fh.flush()


if __name__ == "__main__":
    sim = VehicleSimulator(); sim.start()
    start = time.time()
    print("SDV Simulator running — Ctrl+C to stop\n")
    try:
        while time.time()-start < 30:
            f = sim.get_frame(0.5)
            if f and f["frame_id"] % 10 == 0:
                vio = "⚠️ VIOLATION" if f["iso_violation_detected"] else "✅ OK"
                print(f"[{f['timestamp_ms']:6d}ms] {f['driving_phase']:<22} speed={f['vehicle_speed']:5.1f} delay={f['delay_ms']}ms {vio}")
    except KeyboardInterrupt: pass
    finally: sim.stop()