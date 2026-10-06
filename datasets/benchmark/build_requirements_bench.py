"""
Builds datasets/benchmark/timing_requirements_bench.json (the source of truth is this file).

120 author-written automotive timing requirements with gold labels. They are synthetic
(not taken from industrial specifications) and each category targets one failure mode.

Gold labelling policy
  deadline_ms  overall end-to-end deadline stated or arithmetically derivable; null if absent
  unresolved   true when timing is requested only in vague terms ("promptly")
  component    function area; 'other' when it is none of the KB timing-rule components
  vss_signals  signals the text names or clearly implies (paths from Knowledge_base)
  can_ids      CAN messages the text names (command, feedback, heartbeat, sensor stream)

    python datasets/benchmark/build_requirements_bench.py
"""
import json
from pathlib import Path

OBS = "Vehicle.ADAS.ObstacleDetection.IsWarning"
PED = "Vehicle.ADAS.PedestrianDetection.IsDetected"
PED_CAM = "Vehicle.ADAS.PedestrianDetection.CameraConfidence"
LANE = "Vehicle.ADAS.LaneDepartureDetection.IsWarning"
ACC = "Vehicle.ADAS.CruiseControl.IsActive"
ACC_SET = "Vehicle.ADAS.CruiseControl.SpeedSet"
ABS_A = "Vehicle.ADAS.ABS.IsActive"
ABS_E = "Vehicle.ADAS.ABS.IsEngaged"
ESC = "Vehicle.ADAS.ESC.IsActive"
EBA_A = "Vehicle.ADAS.EBA.IsActive"
BLIGHT = "Vehicle.Body.Lights.Brake.IsActive"
DEB = "Vehicle.Chassis.Brake.IsDriverEmergencyBrakingDetected"
PEDAL = "Vehicle.Chassis.Brake.PedalPosition"
STEER = "Vehicle.Chassis.SteeringWheel.Angle"
SPEED = "Vehicle.Speed"
DRV = "Vehicle.Driver.AttentiveProbability"

BRK, STR, ALR, LDW, ACCC, MON, WDG, OTH = (
    "braking_system", "steering_ecu", "alert_module", "lane_departure_system",
    "acc_system", "safety_monitor", "ecu_watchdog", "other")

BRAKE_CMD, BRAKE_PRESSURE, STEERING_CMD, FUSION, LIDAR, CAMERA, HEARTBEAT, TRACTION = (
    "0x1A0", "0x1A3", "0x210", "0x300", "0x310", "0x320", "0x600", "0x700")

# (text, deadline_ms, component, vss_signals, can_ids, tag[, unresolved])
ROWS = [
    # ── explicit milliseconds ──────────────────────────────────────────────
    ("The emergency braking function shall apply the brakes within 100 ms of detecting an obstacle.", 100, BRK, [OBS], [], "explicit"),
    ("The brake command shall be sent on the CAN bus within 100 ms of an obstacle warning being raised.", 100, BRK, [OBS], [BRAKE_CMD], "explicit"),
    ("Pedestrian detection shall result in braking within 100 ms.", 100, BRK, [PED], [], "explicit"),
    ("Once a pedestrian is detected in the vehicle's path, the system shall brake no later than 100 ms afterwards.", 100, BRK, [PED], [], "explicit"),
    ("The lane departure warning shall be issued within 200 ms of the vehicle leaving its lane.", 200, LDW, [LANE], [], "explicit"),
    ("A lane departure warning must reach the driver within 200 ms.", 200, LDW, [LANE], [], "explicit"),
    ("The adaptive cruise control shall respond to a lead-vehicle speed change within 300 ms.", 300, ACCC, [], [], "explicit"),
    ("Adaptive cruise control shall adjust the set speed within 300 ms of a driver request.", 300, ACCC, [ACC_SET], [], "explicit"),
    ("The driver alert shall be presented within 50 ms of a critical fault being flagged.", 50, ALR, [], [], "explicit"),
    ("A driver alert must be displayed no later than 50 ms after the hazard is detected.", 50, ALR, [], [], "explicit"),
    ("The safety monitor shall activate the safety mechanism within 50 ms of a fault.", 50, MON, [], [], "explicit"),
    ("A safety mechanism activation must occur within 50 ms of fault detection.", 50, MON, [], [], "explicit"),
    ("The ECU watchdog shall time out after 500 ms without a heartbeat.", 500, WDG, [], [HEARTBEAT], "explicit"),
    ("If the zone ECU heartbeat is missing for 500 ms, the watchdog shall trigger a reset.", 500, WDG, [], [HEARTBEAT], "explicit"),
    ("The steering override response shall complete within 200 ms.", 200, STR, [], [], "explicit"),
    ("The steering angle command shall be applied within 200 ms of an emergency steering request.", 200, STR, [STEER], [STEERING_CMD], "explicit"),
    ("ABS shall begin controlling brake pressure within 20 ms of wheel lock-up detection.", 20, BRK, [ABS_E], [], "explicit"),
    ("Electronic stability control shall intervene within 50 ms of a skid being detected.", 50, OTH, [ESC], [], "explicit"),
    ("Traction control shall reduce engine torque within 30 ms of wheel slip detection.", 30, OTH, [], [TRACTION], "explicit"),
    ("The airbag shall deploy within 15 ms of a crash being detected.", 15, OTH, [], [], "explicit"),
    ("The brake lights shall illuminate within 100 ms of the brake pedal being pressed.", 100, OTH, [BLIGHT, PEDAL], [], "explicit"),
    ("Driver emergency braking detection shall raise the emergency brake assist within 100 ms.", 100, BRK, [DEB, EBA_A], [], "explicit"),
    ("The camera detection result shall reach the sensor fusion ECU within 33 ms.", 33, OTH, [], [CAMERA, FUSION], "explicit"),
    ("LiDAR data shall be delivered to the sensor fusion module within 33 ms.", 33, OTH, [], [LIDAR, FUSION], "explicit"),
    ("The pedestrian detection camera confidence shall be updated within 100 ms of new image data.", 100, OTH, [PED_CAM], [], "explicit"),
    ("Brake pressure feedback shall be received within 20 ms of the brake command.", 20, BRK, [], [BRAKE_PRESSURE, BRAKE_CMD], "explicit"),
    ("The vehicle shall display a warning within 50 ms when the driver is detected as inattentive.", 50, ALR, [DRV], [], "explicit"),
    ("Cruise control shall disengage within 100 ms of the brake pedal being pressed.", 100, ACCC, [ACC, PEDAL], [], "explicit"),
    ("Brake pedal position shall be reported within 10 ms.", 10, BRK, [PEDAL], [], "explicit"),
    ("The obstacle detection warning shall reach the driver within 50 ms.", 50, ALR, [OBS], [], "explicit"),
    # ── unit variants ──────────────────────────────────────────────────────
    ("The brakes shall be applied within 0.1 s of obstacle detection.", 100, BRK, [OBS], [], "units"),
    ("Braking must start no later than 0.1 seconds after an obstacle is detected.", 100, BRK, [OBS], [], "units"),
    ("The lane departure warning shall be issued within 0.2 s.", 200, LDW, [LANE], [], "units"),
    ("Steering override shall complete within 0.2 seconds.", 200, STR, [], [], "units"),
    ("The driver alert shall appear within 50 milliseconds of fault detection.", 50, ALR, [], [], "units"),
    ("The watchdog shall expire after half a second without a heartbeat message.", 500, WDG, [], [HEARTBEAT], "units"),
    ("ACC shall respond to a closing lead vehicle within 0.3 s.", 300, ACCC, [], [], "units"),
    ("The safety mechanism shall be active within 5 hundredths of a second of a fault.", 50, MON, [], [], "units"),
    ("The pedestrian braking function shall respond in under a tenth of a second.", 100, BRK, [PED], [], "units"),
    ("The airbag must deploy within 0.015 s of impact detection.", 15, OTH, [], [], "units"),
    ("Time from obstacle detection to full braking must not exceed 0.150 s.", 150, BRK, [OBS], [], "units"),
    ("The emergency brake command shall be issued within 100 msec of detection.", 100, BRK, [], [BRAKE_CMD], "units"),
    ("The warning shall sound within 0.05 s of the lane departure.", 50, LDW, [LANE], [], "units"),
    ("Fault reaction must complete within 2 seconds.", 2000, MON, [], [], "units"),
    ("The steering command shall be output within 0.25 s.", 250, STR, [], [STEERING_CMD], "units"),
    # ── distractor numbers ────────────────────────────────────────────────
    ("At speeds above 80 km/h, the emergency brake shall engage within 120 ms of obstacle detection (ASIL-D).", 120, BRK, [OBS], [], "distractor"),
    ("For obstacles closer than 30 m, braking shall start within 100 ms; the system operates at up to 130 km/h.", 100, BRK, [OBS], [], "distractor"),
    ("The system, rated ASIL-C, shall issue the lane departure warning within 200 ms at 100 km/h.", 200, LDW, [LANE], [], "distractor"),
    ("With a 10 Hz sensor update rate, the pedestrian braking response shall be below 150 ms.", 150, BRK, [PED], [], "distractor"),
    ("On CAN ID 0x1A0, the brake command shall be transmitted within 100 ms of detection.", 100, BRK, [], [BRAKE_CMD], "distractor"),
    ("While the vehicle is travelling at 50 km/h on a 3% gradient, the ACC shall react within 300 ms.", 300, ACCC, [], [], "distractor"),
    ("The 12 V supply may drop, but the safety monitor shall still activate the safety mechanism within 50 ms.", 50, MON, [], [], "distractor"),
    ("Based on a 2 m/s2 deceleration limit, the steering override shall complete within 200 ms.", 200, STR, [], [], "distractor"),
    ("Using three redundant sensors, the watchdog shall reset the ECU within 500 ms of a missing heartbeat.", 500, WDG, [], [HEARTBEAT], "distractor"),
    ("For ASIL-D functions with 99% diagnostic coverage, a driver alert shall be shown within 50 ms.", 50, ALR, [], [], "distractor"),
    ("Under 5 lux lighting, the camera detection shall reach the fusion ECU within 33 ms.", 33, OTH, [], [CAMERA, FUSION], "distractor"),
    ("Within a 40 m range, the obstacle warning shall be displayed in no more than 50 ms.", 50, ALR, [OBS], [], "distractor"),
    ("The system shall brake within 100 ms of a pedestrian detection at a confidence above 0.8.", 100, BRK, [PED], [], "distractor"),
    ("ESC, which samples every 5 ms, shall intervene within 50 ms of skid detection.", 50, OTH, [ESC], [], "distractor"),
    ("At 3 passengers and 20 degrees C, the airbag shall deploy within 15 ms of crash detection.", 15, OTH, [], [], "distractor"),
    # ── multi-clause budgets (gold = the overall deadline) ────────────────
    ("The overall response from obstacle detection to braking shall be within 100 ms, of which perception may use at most 30 ms.", 100, BRK, [OBS], [], "multi_clause"),
    ("End-to-end latency from lane departure to warning must be below 200 ms; the CAN transmission must take under 10 ms.", 200, LDW, [LANE], [], "multi_clause"),
    ("The complete steering override must finish within 200 ms, with the command issued in the first 50 ms.", 200, STR, [], [], "multi_clause"),
    ("The watchdog timeout is 500 ms, and the reset sequence must start within 20 ms of the timeout.", 500, WDG, [], [], "multi_clause"),
    ("Pedestrian detection to full braking: at most 100 ms in total, split 40 ms sensing, 30 ms decision, 30 ms actuation.", 100, BRK, [PED], [], "multi_clause"),
    ("The driver alert latency budget is 50 ms in total, including a 5 ms bus delay.", 50, ALR, [], [], "multi_clause"),
    ("ACC must react within 300 ms; the brake request part must be sent within 100 ms.", 300, ACCC, [], [], "multi_clause"),
    ("Safety mechanism activation, including diagnosis (20 ms) and reaction (30 ms), must complete within 50 ms.", 50, MON, [], [], "multi_clause"),
    ("Total time from crash detection to airbag deployment shall be 15 ms, of which 5 ms is sensor processing.", 15, OTH, [], [], "multi_clause"),
    ("From brake pedal press to brake light illumination, a maximum of 100 ms is allowed, with the lamp driver contributing at most 20 ms.", 100, OTH, [PEDAL, BLIGHT], [], "multi_clause"),
    # ── no timing requirement at all ──────────────────────────────────────
    ("The emergency braking function shall log every activation event.", None, BRK, [], [], "no_deadline"),
    ("The lane departure warning shall be both audible and visual.", None, LDW, [LANE], [], "no_deadline"),
    ("The driver shall be able to disable adaptive cruise control.", None, ACCC, [ACC], [], "no_deadline"),
    ("The steering system shall support wheel angles up to 540 degrees.", None, STR, [STEER], [], "no_deadline"),
    ("Brake pressure shall not exceed 200 bar.", None, BRK, [], [], "no_deadline"),
    ("The watchdog shall be implemented in a separate hardware unit.", None, WDG, [], [], "no_deadline"),
    ("The pedestrian detection function shall use camera and LiDAR inputs.", None, OTH, [PED], [], "no_deadline"),
    ("The airbag control unit shall be diagnosable via OBD.", None, OTH, [], [], "no_deadline"),
    ("All safety messages shall be authenticated.", None, OTH, [], [], "no_deadline"),
    ("The safety monitor shall report its status in the vehicle log.", None, MON, [], [], "no_deadline"),
    ("Vehicle speed shall be reported in km/h.", None, OTH, [SPEED], [], "no_deadline"),
    ("ABS shall be active in all driving modes.", None, BRK, [ABS_A], [], "no_deadline"),
    ("The infotainment system shall not affect safety-critical CAN traffic.", None, OTH, [], [], "no_deadline"),
    ("The ECU shall restart automatically after a watchdog reset.", None, WDG, [], [], "no_deadline"),
    ("Traction control shall be operable on icy roads.", None, OTH, [], [TRACTION], "no_deadline"),
    # ── vague timing (cannot be turned into a number) ─────────────────────
    ("The emergency brake shall engage as soon as possible after an obstacle is detected.", None, BRK, [OBS], [], "vague", True),
    ("The lane departure warning shall be issued promptly.", None, LDW, [LANE], [], "vague", True),
    ("The driver alert shall appear without perceptible delay.", None, ALR, [], [], "vague", True),
    ("ACC shall react quickly to changes in lead vehicle speed.", None, ACCC, [], [], "vague", True),
    ("The system shall brake in a timely manner when a pedestrian is detected.", None, BRK, [PED], [], "vague", True),
    ("Steering override shall be performed in real time.", None, STR, [], [], "vague", True),
    ("The watchdog shall trigger a reset shortly after the heartbeat is lost.", None, WDG, [], [HEARTBEAT], "vague", True),
    ("Safety mechanisms shall react with minimal latency.", None, MON, [], [], "vague", True),
    ("The airbag must deploy immediately on impact.", None, OTH, [], [], "vague", True),
    ("The obstacle warning shall be displayed within a short time.", None, ALR, [OBS], [], "vague", True),
    # ── derived by arithmetic or paraphrase ───────────────────────────────
    ("Braking shall start within five control cycles of 10 ms after obstacle detection.", 50, BRK, [OBS], [], "derived"),
    ("The lane departure warning shall be generated within 4 cycles of the 50 ms task.", 200, LDW, [LANE], [], "derived"),
    ("The watchdog expires after three missed 100 ms heartbeats.", 300, WDG, [], [HEARTBEAT], "derived"),
    ("ACC shall respond within two sampling periods of 150 ms.", 300, ACCC, [], [], "derived"),
    ("The brake command shall be sent within one tenth of a second of detection.", 100, BRK, [], [BRAKE_CMD], "derived"),
    ("The driver alert shall appear within twice the 25 ms sensor period.", 50, ALR, [], [], "derived"),
    ("The steering override shall finish within double the 100 ms nominal time.", 200, STR, [], [], "derived"),
    ("Safety mechanism activation shall take no longer than half of the 100 ms emergency brake budget.", 50, MON, [], [], "derived"),
    ("Pedestrian braking must be 20 ms faster than the 120 ms general braking limit.", 100, BRK, [PED], [], "derived"),
    ("The airbag deploys within three 5 ms sensor frames.", 15, OTH, [], [], "derived"),
    ("Brake pressure feedback shall arrive within 2 ms of the brake actuator update.", 2, BRK, [], [BRAKE_PRESSURE], "derived"),
    ("The fusion output shall be available within one 20 ms cycle of the camera detection.", 20, OTH, [], [FUSION, CAMERA], "derived"),
    ("The warning must be issued within a fifth of a second of the lane departure.", 200, LDW, [LANE], [], "derived"),
    ("Cruise control disengagement on braking must take less than 100 ms, or one tenth of a second.", 100, ACCC, [ACC, PEDAL], [], "derived"),
    ("Steering response is allowed 0.4 s minus the 0.2 s already used by perception.", 200, STR, [], [], "derived"),
    # ── unusual formats ───────────────────────────────────────────────────
    ("Brake within 100ms if obstacle detected.", 100, BRK, [OBS], [], "format"),
    ("Obstacle-to-brake latency <= 100 ms.", 100, BRK, [OBS], [], "format"),
    ("t(obstacle_detected -> brake_applied) < 100 ms", 100, BRK, [OBS], [], "format"),
    ("REQ-BRK-001: Emergency brake actuation SHALL occur within 100 MILLISECONDS of obstacle detection.", 100, BRK, [OBS], [], "format"),
    ("LDW alert <= 200ms from lane crossing.", 200, LDW, [LANE], [], "format"),
    ("Heartbeat timeout: 500 msec.", 500, WDG, [], [HEARTBEAT], "format"),
    ("Max latency, pedestrian detection to brake: 0.1 s.", 100, BRK, [PED], [], "format"),
    ("ACC response time limit - 300 ms (see HARA item 12).", 300, ACCC, [], [], "format"),
    ("Driver alert SLA: fifty milliseconds.", 50, ALR, [], [], "format"),
    ("The AEB must be fully engaged inside of one hundred milliseconds of obstacle detection.", 100, BRK, [OBS], [], "format"),
]


def build():
    items = []
    for i, row in enumerate(ROWS, start=1):
        text, deadline, component, signals, can_ids, tag = row[:6]
        items.append({
            "id": f"R{i:03d}", "text": text, "deadline_ms": deadline, "unresolved": bool(len(row) > 6 and row[6]),
            "component": component, "vss_signals": signals, "can_ids": can_ids, "tags": [tag],
        })
    return items


if __name__ == "__main__":
    items = build()
    out = Path(__file__).with_name("timing_requirements_bench.json")
    out.write_text(json.dumps(items, indent=1), encoding="utf-8")
    counts = {}
    for it in items:
        counts[it["tags"][0]] = counts.get(it["tags"][0], 0) + 1
    print(f"wrote {len(items)} requirements to {out}")
    print(counts)
