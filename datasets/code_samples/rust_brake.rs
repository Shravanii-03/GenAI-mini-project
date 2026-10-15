/// brake_rust.rs — SDV Emergency Braking System (Rust)
/// Used for MODULE 1: Multi-Language Code Analyzer testing
/// Rust is memory-safe by design — promising for ASIL-D automotive
/// CAN IDs and VSS signal names embedded for parser extraction

use std::time::{Duration, Instant};

// ──────────────────────────────────────────────────────────
// CAN Message IDs
// ──────────────────────────────────────────────────────────
const CAN_BRAKE_CMD: u32      = 0x1A0;
const CAN_BRAKE_FEEDBACK: u32 = 0x1A3;
const CAN_SENSOR_FUSION: u32  = 0x300;
const CAN_CAMERA_DETECT: u32  = 0x320;
const CAN_LIDAR_DATA: u32     = 0x310;
const CAN_SPEED: u32          = 0x200;

// ──────────────────────────────────────────────────────────
// VSS Signal Paths
// ──────────────────────────────────────────────────────────
const VSS_PEDESTRIAN_DETECTED: &str  = "Vehicle.ADAS.PedestrianDetection.IsDetected";
const VSS_CAMERA_CONFIDENCE: &str    = "Vehicle.ADAS.PedestrianDetection.CameraConfidence";
const VSS_LIDAR_CONFIDENCE: &str     = "Vehicle.ADAS.PedestrianDetection.LidarConfidence";
const VSS_BRAKE_ACTIVE: &str         = "Vehicle.ADAS.EBA.IsActive";
const VSS_SPEED: &str                = "Vehicle.Speed";

// ──────────────────────────────────────────────────────────
// ISO 26262 timing constraints
// ──────────────────────────────────────────────────────────
const MAX_BRAKE_LATENCY_MS: u64     = 100;  // ISO26262-6-8.4.5
const MAX_DETECTION_LATENCY_MS: u64  = 50;
const PEDESTRIAN_CONF_THRESH: f32    = 0.75;
const LIDAR_DISTANCE_THRESH_M: f32   = 5.0;

// ──────────────────────────────────────────────────────────
// CAN Frame struct
// ──────────────────────────────────────────────────────────
#[derive(Debug)]
struct CanFrame {
    id: u32,
    dlc: u8,
    data: [u8; 8],
}

// ──────────────────────────────────────────────────────────
// Simulated CAN send
// ──────────────────────────────────────────────────────────
fn send_can(can_id: u32, data: &[u8; 8], _len: u8) {
    println!("[CAN TX] ID=0x{:X} DLC={}", can_id, data.len());
    // In production: write to socketcan or AUTOSAR Com interface
}

// ──────────────────────────────────────────────────────────
// Step 1: Sense — camera data acquisition
// ──────────────────────────────────────────────────────────
#[derive(Debug)]
struct CameraResult {
    confidence: f32,
    pedestrian_raw: bool,
    latency_ms: u64,
    vss_signal: &'static str,
}

fn capture_camera_data() -> CameraResult {
    let t_start = Instant::now();
    
    // Simulate CAN frame 0x320 CAMERA_DETECT
    let frame = CanFrame {
        id: CAN_CAMERA_DETECT,
        dlc: 8,
        data: [0x02, 0x00, 0x50, 0x64, 0x00, 0x50, 0x00, 0x00],
    };
    
    let confidence = (frame.data[5] as f32) / 100.0;
    let pedestrian_raw = (frame.data[0] >> 1) & 1 == 1;
    let latency_ms = t_start.elapsed().as_millis() as u64;
    
    CameraResult {
        confidence,
        pedestrian_raw,
        latency_ms,
        vss_signal: VSS_CAMERA_CONFIDENCE,
    }
}

// ──────────────────────────────────────────────────────────
// Step 2: Detect — pedestrian classification
// ──────────────────────────────────────────────────────────
fn detect_pedestrian_camera(cam: &CameraResult) -> bool {
    cam.confidence > PEDESTRIAN_CONF_THRESH
}

fn detect_pedestrian_lidar() -> bool {
    // Simulate CAN frame 0x310 LIDAR_DATA
    let frame = CanFrame {
        id: CAN_LIDAR_DATA,
        dlc: 8,
        data: [0x00, 0x64, 0x01, 0x2C, 0x01, 0x00, 0x00, 0x00],
    };
    
    let raw_dist = ((frame.data[2] as u16) << 8) | frame.data[3] as u16;
    let nearest_m = (raw_dist as f32) * 0.01;
    
    nearest_m < LIDAR_DISTANCE_THRESH_M
}

// ──────────────────────────────────────────────────────────
// Step 3: Decide — sensor fusion per ISO 26262
// ──────────────────────────────────────────────────────────
fn brake_decision(cam_detected: bool, lidar_detected: bool) -> bool {
    // ISO 26262 Rule EC-004: brake AFTER pedestrian_detected
    cam_detected || lidar_detected
}

// ──────────────────────────────────────────────────────────
// Step 4: Actuate — send CAN BRAKE_CMD
// ──────────────────────────────────────────────────────────
#[derive(Debug)]
struct BrakeResult {
    pressure_bar: f32,
    latency_ms: u64,
    vss_signal: &'static str,
    can_id: u32,
}

fn emergency_brake(pressure_bar: f32) -> BrakeResult {
    let t_start = Instant::now();
    
    let pressure_raw = pressure_bar as u16;
    let mut data = [0u8; 8];
    data[0] = ((pressure_raw >> 8) & 0xFF) as u8;
    data[1] = (pressure_raw & 0xFF) as u8;
    data[2] = 0x01;  // brake_active
    data[3] = 0x01;  // emergency_flag
    
    send_can(CAN_BRAKE_CMD, &data, 8);
    
    BrakeResult {
        pressure_bar,
        latency_ms: t_start.elapsed().as_millis() as u64,
        vss_signal: VSS_BRAKE_ACTIVE,
        can_id: CAN_BRAKE_CMD,
    }
}

// ──────────────────────────────────────────────────────────
// Full event chain
// ──────────────────────────────────────────────────────────
#[derive(Debug)]
struct CycleResult {
    total_latency_ms: u64,
    violation: bool,
    pedestrian_detected: bool,
}

fn run_emergency_brake_cycle() -> CycleResult {
    let t_cycle_start = Instant::now();
    
    // Step 1: Sense
    let cam = capture_camera_data();
    
    // Step 2: Detect
    let cam_ped   = detect_pedestrian_camera(&cam);
    let lidar_ped = detect_pedestrian_lidar();
    
    // Step 3: Decide
    let should_brake = brake_decision(cam_ped, lidar_ped);
    
    // Step 4: Actuate
    if should_brake {
        let _brake = emergency_brake(150.0);
    }
    
    let total_latency_ms = t_cycle_start.elapsed().as_millis() as u64;
    let violation = total_latency_ms > MAX_BRAKE_LATENCY_MS;
    
    CycleResult {
        total_latency_ms,
        violation,
        pedestrian_detected: should_brake,
    }
}

fn main() {
    println!("[SDV Brake Rust] Starting emergency brake cycle...");
    let result = run_emergency_brake_cycle();
    println!(
        "[SDV Brake Rust] Latency: {}ms | Violation: {} | Pedestrian: {}",
        result.total_latency_ms,
        if result.violation { "YES" } else { "NO" },
        if result.pedestrian_detected { "YES" } else { "NO" }
    );
    
    if result.violation {
        std::process::exit(1);
    }
}