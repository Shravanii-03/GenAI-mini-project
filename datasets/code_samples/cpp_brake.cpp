/**
 * brake_cpp.cpp — SDV Emergency Braking System (C++ / Zone ECU style)
 * Used for MODULE 1: Multi-Language Code Analyzer testing
 * Target: automotive Zone ECU / AUTOSAR-inspired
 * CAN IDs and VSS-equivalent signal names embedded for parser extraction
 */

#include <iostream>
#include <cstdint>
#include <chrono>
#include <thread>
#include <stdexcept>

// ──────────────────────────────────────────────────────────
// CAN Message IDs
// ──────────────────────────────────────────────────────────
#define CAN_BRAKE_CMD        0x1A0
#define CAN_BRAKE_FEEDBACK   0x1A3
#define CAN_SENSOR_FUSION    0x300
#define CAN_CAMERA_DETECT    0x320
#define CAN_LIDAR_DATA       0x310
#define CAN_SPEED            0x200

// ──────────────────────────────────────────────────────────
// VSS Signal Names (string constants for logging/comm)
// ──────────────────────────────────────────────────────────
constexpr const char* VSS_PEDESTRIAN_DETECTED  = "Vehicle.ADAS.PedestrianDetection.IsDetected";
constexpr const char* VSS_CAMERA_CONFIDENCE    = "Vehicle.ADAS.PedestrianDetection.CameraConfidence";
constexpr const char* VSS_LIDAR_CONFIDENCE     = "Vehicle.ADAS.PedestrianDetection.LidarConfidence";
constexpr const char* VSS_BRAKE_ACTIVE         = "Vehicle.ADAS.EBA.IsActive";
constexpr const char* VSS_SPEED                = "Vehicle.Speed";

// ──────────────────────────────────────────────────────────
// Timing constraints (ISO 26262 ASIL-D)
// ──────────────────────────────────────────────────────────
constexpr int MAX_BRAKE_LATENCY_MS     = 100;   // ISO26262-6-8.4.5
constexpr int MAX_DETECTION_LATENCY_MS  = 50;
constexpr float PEDESTRIAN_CONF_THRESH  = 0.75f;
constexpr float LIDAR_DISTANCE_THRESH_M = 5.0f;

// ──────────────────────────────────────────────────────────
// Simulated CAN frame structure
// ──────────────────────────────────────────────────────────
struct CanFrame {
    uint32_t id;
    uint8_t  dlc;
    uint8_t  data[8];
};

// ──────────────────────────────────────────────────────────
// Simulated CAN send (replace with real socketcan or AUTOSAR Com)
// ──────────────────────────────────────────────────────────
void send_can(uint32_t can_id, const uint8_t* data, uint8_t len) {
    std::cout << "[CAN TX] ID=" << std::hex << can_id << " DLC=" << (int)len << std::dec << std::endl;
    // In production: write() to socketcan fd or AUTOSAR COM SendSignal()
}

// ──────────────────────────────────────────────────────────
// Step 1: Sense — capture camera detection frame
// ──────────────────────────────────────────────────────────
struct CameraResult {
    float confidence;
    bool  pedestrian_raw;
    int   latency_ms;
};

CameraResult capture_camera_data() {
    auto t_start = std::chrono::steady_clock::now();
    
    // Simulate receiving CAN frame 0x320 CAMERA_DETECT
    CanFrame frame = {CAN_CAMERA_DETECT, 8, {0x02, 0x00, 0x50, 0x64, 0x00, 0x50, 0x00, 0x00}};
    
    float confidence = frame.data[5] / 100.0f;  // byte 5 = confidence percent
    bool ped_raw = (frame.data[0] >> 1) & 1;
    
    auto t_end = std::chrono::steady_clock::now();
    int latency = std::chrono::duration_cast<std::chrono::milliseconds>(t_end - t_start).count();
    
    return {confidence, ped_raw, latency};
}

// ──────────────────────────────────────────────────────────
// Step 2: Detect — classify pedestrian
// ──────────────────────────────────────────────────────────
bool detect_pedestrian_camera(const CameraResult& cam) {
    return cam.confidence > PEDESTRIAN_CONF_THRESH;
}

bool detect_pedestrian_lidar() {
    // Simulate receiving CAN frame 0x310 LIDAR_DATA
    CanFrame frame = {CAN_LIDAR_DATA, 8, {0x00, 0x64, 0x01, 0x2C, 0x01, 0x00, 0x00, 0x00}};
    
    // nearest_object_m = bytes[2:4] * 0.01
    uint16_t raw_dist = (static_cast<uint16_t>(frame.data[2]) << 8) | frame.data[3];
    float nearest_m = raw_dist * 0.01f;
    
    return nearest_m < LIDAR_DISTANCE_THRESH_M;
}

// ──────────────────────────────────────────────────────────
// Step 3: Decide — fuse sensors per ISO 26262
// ──────────────────────────────────────────────────────────
bool brake_decision(bool cam_detected, bool lidar_detected) {
    // ISO 26262 Rule EC-004: brake AFTER pedestrian_detected
    return cam_detected || lidar_detected;
}

// ──────────────────────────────────────────────────────────
// Step 4: Actuate — send CAN BRAKE_CMD (0x1A0)
// ──────────────────────────────────────────────────────────
struct BrakeResult {
    float pressure_bar;
    int   latency_ms;
    bool  success;
};

BrakeResult emergency_brake(float pressure_bar = 150.0f) {
    auto t_start = std::chrono::steady_clock::now();
    
    uint16_t pressure_raw = static_cast<uint16_t>(pressure_bar);
    uint8_t data[8] = {
        static_cast<uint8_t>((pressure_raw >> 8) & 0xFF),  // high byte
        static_cast<uint8_t>(pressure_raw & 0xFF),          // low byte
        0x01,                                                // brake_active
        0x01,                                                // emergency_flag
        0x00, 0x00, 0x00, 0x00
    };
    
    send_can(CAN_BRAKE_CMD, data, 8);
    
    auto t_end = std::chrono::steady_clock::now();
    int latency = std::chrono::duration_cast<std::chrono::milliseconds>(t_end - t_start).count();
    
    return {pressure_bar, latency, true};
}

// ──────────────────────────────────────────────────────────
// Main event chain
// ──────────────────────────────────────────────────────────
struct CycleResult {
    int  total_latency_ms;
    bool violation;
    bool pedestrian_detected;
};

CycleResult run_emergency_brake_cycle() {
    auto t_cycle_start = std::chrono::steady_clock::now();
    
    // Step 1: Sense
    CameraResult cam = capture_camera_data();
    
    // Step 2: Detect
    bool cam_ped   = detect_pedestrian_camera(cam);
    bool lidar_ped = detect_pedestrian_lidar();
    
    // Step 3: Decide
    bool should_brake = brake_decision(cam_ped, lidar_ped);
    
    // Step 4: Actuate
    if (should_brake) {
        emergency_brake(150.0f);
    }
    
    auto t_cycle_end = std::chrono::steady_clock::now();
    int total_latency = std::chrono::duration_cast<std::chrono::milliseconds>(
        t_cycle_end - t_cycle_start).count();
    
    bool violation = total_latency > MAX_BRAKE_LATENCY_MS;
    
    return {total_latency, violation, should_brake};
}

int main() {
    std::cout << "[SDV Brake C++] Starting emergency brake cycle..." << std::endl;
    
    CycleResult result = run_emergency_brake_cycle();
    
    std::cout << "[SDV Brake C++] Latency: " << result.total_latency_ms
              << "ms | Violation: " << (result.violation ? "YES" : "NO")
              << " | Pedestrian: " << (result.pedestrian_detected ? "YES" : "NO")
              << std::endl;
    
    return result.violation ? 1 : 0;
}