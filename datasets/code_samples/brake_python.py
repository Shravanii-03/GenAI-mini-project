"""
brake_python.py — SDV Emergency Braking System (Python / digital.auto style)
Used for MODULE 1: Multi-Language Code Analyzer testing
VSS signals and CAN IDs are embedded — to be extracted by multi_lang_parser.py
"""

import time
import can  # python-can library

# ──────────────────────────────────────────────────────────
# VSS Signal bindings
# ──────────────────────────────────────────────────────────
VSS_PEDESTRIAN_DETECTED   = "Vehicle.ADAS.PedestrianDetection.IsDetected"
VSS_CAMERA_CONFIDENCE     = "Vehicle.ADAS.PedestrianDetection.CameraConfidence"
VSS_LIDAR_CONFIDENCE      = "Vehicle.ADAS.PedestrianDetection.LidarConfidence"
VSS_BRAKE_PEDAL           = "Vehicle.Chassis.Brake.PedalPosition"
VSS_SPEED                 = "Vehicle.Speed"
VSS_EBA_ACTIVE            = "Vehicle.ADAS.EBA.IsActive"

# ──────────────────────────────────────────────────────────
# CAN Message IDs
# ──────────────────────────────────────────────────────────
CAN_BRAKE_CMD      = 0x1A0   # BRAKE_CMD
CAN_BRAKE_FEEDBACK = 0x1A3   # BRAKE_PRESSURE
CAN_SENSOR_FUSION  = 0x300   # SENSOR_FUSION
CAN_CAMERA_DETECT  = 0x320   # CAMERA_DETECT
CAN_LIDAR_DATA     = 0x310   # LIDAR_DATA

# ──────────────────────────────────────────────────────────
# Timing thresholds (ISO 26262)
# ──────────────────────────────────────────────────────────
MAX_BRAKE_LATENCY_MS    = 100   # ISO26262-6-8.4.5
MAX_DETECTION_LATENCY_MS = 50

# ──────────────────────────────────────────────────────────
# CAN Bus setup
# ──────────────────────────────────────────────────────────
bus = can.interface.Bus(channel='vcan0', bustype='socketcan')


def capture_camera_data() -> dict:
    """Step 1: Sense — capture camera frame and read CAN detection result."""
    t_start = time.time_ns() // 1_000_000
    msg = bus.recv(timeout=0.05)  # 50ms timeout
    if msg and msg.arbitration_id == CAN_CAMERA_DETECT:
        confidence = msg.data[5]  # byte 5 = detection confidence
        pedestrian_flag = (msg.data[0] >> 1) & 1
        return {
            "vss_signal": VSS_CAMERA_CONFIDENCE,
            "can_id": hex(CAN_CAMERA_DETECT),
            "confidence": confidence / 100.0,
            "pedestrian_raw": pedestrian_flag,
            "latency_ms": (time.time_ns() // 1_000_000) - t_start
        }
    return {"vss_signal": VSS_CAMERA_CONFIDENCE, "confidence": 0.0, "latency_ms": 0}


def detect_pedestrian_camera(camera_data: dict) -> bool:
    """Step 2: Detect — classify pedestrian from camera data."""
    confidence = camera_data.get("confidence", 0.0)
    return confidence > 0.75


def detect_pedestrian_lidar() -> bool:
    """Step 2b: Detect — LIDAR-based pedestrian detection."""
    msg = bus.recv(timeout=0.033)  # 33ms
    if msg and msg.arbitration_id == CAN_LIDAR_DATA:
        nearest_m = int.from_bytes(msg.data[2:4], 'big') * 0.01
        return nearest_m < 5.0  # pedestrian within 5m
    return False


def brake_decision(cam_detected: bool, lidar_detected: bool) -> bool:
    """Step 3: Decide — fuse camera and LIDAR decision."""
    # ISO 26262 rule: brake if EITHER sensor detects pedestrian
    return cam_detected or lidar_detected


def emergency_brake(pressure_bar: float = 150.0):
    """Step 4: Actuate — send emergency brake CAN command."""
    t_start = time.time_ns() // 1_000_000
    
    # Build CAN frame for BRAKE_CMD (0x1A0)
    pressure_raw = int(pressure_bar)
    data = [
        (pressure_raw >> 8) & 0xFF,   # brake_pressure high byte
        pressure_raw & 0xFF,           # brake_pressure low byte
        0x01,                          # brake_active = 1
        0x01,                          # emergency_flag = 1
        0x00, 0x00, 0x00, 0x00        # padding
    ]
    msg = can.Message(arbitration_id=CAN_BRAKE_CMD, data=data, is_extended_id=False)
    bus.send(msg)
    
    latency = (time.time_ns() // 1_000_000) - t_start
    return {
        "vss_signal": VSS_EBA_ACTIVE,
        "can_id": hex(CAN_BRAKE_CMD),
        "pressure_bar": pressure_bar,
        "latency_ms": latency
    }


def run_emergency_brake_cycle():
    """
    Full event chain:
    capture_camera_data → detect_pedestrian_camera → detect_pedestrian_lidar
    → brake_decision → emergency_brake
    
    ISO 26262 constraint: total latency must be < MAX_BRAKE_LATENCY_MS (100ms)
    """
    t_cycle_start = time.time_ns() // 1_000_000
    
    # Step 1: Sense
    camera_data = capture_camera_data()
    
    # Step 2: Detect
    cam_ped = detect_pedestrian_camera(camera_data)
    lidar_ped = detect_pedestrian_lidar()
    
    # Step 3: Decide
    should_brake = brake_decision(cam_ped, lidar_ped)
    
    # Step 4: Actuate
    result = None
    if should_brake:
        result = emergency_brake(pressure_bar=150.0)
    
    total_latency = (time.time_ns() // 1_000_000) - t_cycle_start
    violation = total_latency > MAX_BRAKE_LATENCY_MS
    
    return {
        "total_latency_ms": total_latency,
        "violation": violation,
        "pedestrian_detected": should_brake,
        "brake_result": result
    }


if __name__ == "__main__":
    print("[SDV Brake] Starting emergency brake cycle...")
    result = run_emergency_brake_cycle()
    print(f"[SDV Brake] Latency: {result['total_latency_ms']}ms | Violation: {result['violation']}")